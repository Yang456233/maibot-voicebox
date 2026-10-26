import asyncio
import base64
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from conftest import plugin_module as mod
from voicebox_plugin.voicebox.providers import Audio, VoiceError


def messages():
    return [{"segments": [{"type": "text", "data": "你好。"}, {"type": "image", "data": "猫", "hash": "cat"}], "quote_previous": True},
            {"segments": [{"type": "text", "data": "今天开心吗？"}], "quote_previous": False}]


async def invoke(p, **changes):
    args = dict(phase="before_send", session_id="s", reply_id="r", call_id="c", chat={"platform": "qq"}, messages=messages())
    args.update(changes)
    return await p.voice_reply(**args)


@pytest.mark.asyncio
async def test_reply_preserves_attachment_history_and_no_manual_send(plugin, wav):
    plugin.engine.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    result = await invoke(plugin)
    segments = result["messages"][0]["segments"]
    assert segments[0]["type"] == "voice" and segments[0]["data"] == "你好。\n今天开心吗？"
    assert segments[1]["hash"] == "cat"
    assert result["messages"][0]["quote_previous"]
    plugin.ctx.send.custom.assert_not_awaited()
    assert await invoke(plugin) == {}
    assert plugin.engine.synthesize.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [VoiceError("超时"), ValueError("bad")])
async def test_failure_keeps_original(plugin, failure):
    plugin.engine.synthesize = AsyncMock(side_effect=failure)
    assert await invoke(plugin) == {}
    plugin.ctx.send.text.assert_not_awaited()


@pytest.mark.asyncio
async def test_japanese_original_is_kept(plugin, wav):
    plugin.state.update("s", language="日语")
    plugin.engine.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    result = await invoke(plugin)
    texts = [s["data"] for m in result["messages"] for s in m["segments"] if s["type"] == "text"]
    assert texts == ["你好。", "今天开心吗？"]


@pytest.mark.asyncio
async def test_existing_voice_and_text_mode_not_reprocessed(plugin, wav):
    plugin.engine.synthesize = AsyncMock()
    existing = [{"segments": [{"type": "voice", "data": "hi", "binary_data_base64": base64.b64encode(wav).decode()}], "quote_previous": False}]
    assert await invoke(plugin, messages=existing) == {}
    plugin.state.update("s", mode="文字")
    assert await invoke(plugin) == {}
    plugin.engine.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_next_persists_and_only_one_synthesis(plugin, wav):
    plugin.state.update("s", next=True)
    await plugin.on_config_update("self", {}, "0.1.0")
    assert plugin.state.get("s")["next"]
    plugin.engine.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    await invoke(plugin)
    assert not plugin.state.get("s")["next"]


@pytest.mark.asyncio
async def test_planner_routes_only_reply_and_preserves_other_options(plugin):
    plugin.sessions["s"] = "qq"
    plugin.state.update("s", mode="持续", next=True)
    data = {"session_id": "s", "item_schema_version": 1, "output_items": [
        {"tool_call": {"func_name": "reply", "args": {"msg_id": "m", "plugin_options": {"other": {"a": 1}}}}},
        {"tool_call": {"func_name": "notification", "args": {}}}]}
    result = await plugin.plan_reply(**deepcopy(data))
    items = result["modified_kwargs"]["output_items"]
    assert items[0]["tool_call"]["args"]["plugin_options"]["other"] == {"a": 1}
    assert mod.EXTENSION in items[0]["tool_call"]["args"]["plugin_options"]
    assert items[1] == data["output_items"][1]
    plugin.state.update("s", mode="文字")
    result = await plugin.plan_reply(**result["modified_kwargs"])
    assert mod.EXTENSION not in result["modified_kwargs"]["output_items"][0]["tool_call"]["args"]["plugin_options"]


@pytest.mark.asyncio
async def test_explicit_request_is_message_bound(plugin):
    await plugin.receive(message={"platform": "qq", "session_id": "s", "message_id": "m", "raw_message": [{"type": "text", "data": "请用语音回复我"}]})
    data = {"session_id": "s", "output_items": [{"tool_call": {"func_name": "reply", "args": {"msg_id": mid}}} for mid in ["other", "m"]]}
    result = (await plugin.plan_reply(**data))["modified_kwargs"]["output_items"]
    assert mod.EXTENSION not in result[0]["tool_call"]["args"]["plugin_options"]
    assert mod.EXTENSION in result[1]["tool_call"]["args"]["plugin_options"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sent,count", [(False, 1), (True, 0), (None, 0)])
async def test_delivery_fallback_exactly_once(plugin, wav, sent, count):
    plugin.engine.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    result = await invoke(plugin)
    message = {"session_id": "s", "raw_message": result["messages"][0]["segments"]}
    await plugin.after_send(message=message, sent=sent)
    await plugin.after_send(message=message, sent=False)
    assert plugin.ctx.send.text.await_count == count


@pytest.mark.asyncio
async def test_group_permission_and_private_isolation(plugin):
    await plugin.command(stream_id="group", platform="qq", user_id="7", group_id="g", matched_groups={"args": "模式 持续"})
    assert plugin.state.get("group")["mode"] == "自动"
    await plugin.command(stream_id="group", platform="qq", user_id="42", group_id="g", matched_groups={"args": "模式 持续"})
    assert plugin.state.get("group")["mode"] == "持续"
    await plugin.command(stream_id="private7", platform="qq", user_id="7", matched_groups={"args": "语言 日语"})
    assert plugin.state.get("private7")["language"] == "日语"
    assert plugin.state.get("private8")["language"] == "原文"


@pytest.mark.asyncio
async def test_preview_does_not_bind_and_failure_dict_checked(plugin, wav):
    plugin.engine.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    plugin.ctx.send.custom.return_value = {"sent": False, "message_id": "x"}
    await plugin.command(stream_id="s", platform="qq", user_id="7", matched_groups={"args": "试听 xiaoxiao"})
    assert plugin.state.get("s")["role"] == ""
    assert plugin.ctx.send.text.await_count == 1


@pytest.mark.asyncio
async def test_unknown_delivery_no_retry(plugin, wav):
    plugin.engine.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    plugin.ctx.send.custom.side_effect = TimeoutError()
    await plugin.command_audio("s", "你好", plugin.roles.find("xiaoxiao"), "原文", "")
    plugin.ctx.send.text.assert_not_awaited()


def test_schema_is_generated():
    schema = mod.VoiceboxPlugin.build_config_schema()
    assert schema and "角色" in str(schema)


@pytest.mark.asyncio
async def test_planner_lists_real_emotions_and_hides_in_text_mode(plugin):
    schema = {"type": "object", "properties": {"emotion": {"type": "string"}}, "description": "voice"}
    payload = {"session_id": "s", "tool_definitions": [{"type": "function", "function": {"name": "reply",
        "parameters": {"properties": {"plugin_options": {"properties": {mod.EXTENSION: schema}}}}}}]}
    result = await plugin.describe_voice(**deepcopy(payload))
    options = result["modified_kwargs"]["tool_definitions"][0]["function"]["parameters"]["properties"]["plugin_options"]["properties"]
    assert options[mod.EXTENSION]["properties"]["emotion"]["enum"] == [""]
    plugin.state.update("s", role="xingnai")
    result = await plugin.describe_voice(**deepcopy(payload))
    options = result["modified_kwargs"]["tool_definitions"][0]["function"]["parameters"]["properties"]["plugin_options"]["properties"]
    assert options[mod.EXTENSION]["properties"]["emotion"]["enum"] == ["", "日常"]
    plugin.state.update("s", mode="文字")
    result = await plugin.describe_voice(**deepcopy(payload))
    assert mod.EXTENSION not in result["modified_kwargs"]["tool_definitions"][0]["function"]["parameters"]["properties"]["plugin_options"]["properties"]


@pytest.mark.asyncio
async def test_japanese_definite_failure_restores_chinese(plugin, wav):
    plugin.state.update("s", language="日语")
    plugin.engine.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    result = await invoke(plugin)
    await plugin.after_send(message={"session_id": "s", "raw_message": result["messages"][0]["segments"]}, sent=False)
    plugin.ctx.send.text.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_permission_denied(plugin):
    await plugin.command(stream_id="s", user_id="7", platform="qq", matched_groups={"args": "导入 nonexistent"})
    assert "管理员" in plugin.ctx.send.text.call_args.args[0]
