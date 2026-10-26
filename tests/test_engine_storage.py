import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from voicebox_plugin.voicebox.providers import Audio, VoiceError, checked_audio, IndexProvider
from voicebox_plugin.voicebox.config import Emotion, IndexSettings
from voicebox_plugin.voicebox.storage import State, safe_file


@pytest.mark.asyncio
async def test_cache_and_config_fingerprint(plugin, wav):
    provider = plugin.engine.providers["edge"]
    provider.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    role = plugin.roles.find("xiaoxiao")
    await plugin.engine.synthesize("a", "你好", role)
    await plugin.engine.synthesize("b", "你好", role)
    assert provider.synthesize.await_count == 1
    role.pitch = 2
    await plugin.engine.synthesize("b", "你好", role)
    assert provider.synthesize.await_count == 2
    plugin.ctx.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"success": False, "response": ""}, {"success": True, "response": ""}, {"success": True, "response": "English only"}])
async def test_translation_failures(plugin, result):
    plugin.ctx.llm.generate.return_value = result
    provider = plugin.engine.providers["edge"]
    provider.synthesize = AsyncMock()
    with pytest.raises(VoiceError):
        await plugin.engine.synthesize("a", "你好", plugin.roles.find("xiaoxiao"), "日语")
    provider.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_japanese_translation_and_language_validation(plugin, wav):
    provider = plugin.engine.providers["edge"]
    provider.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    role = plugin.roles.find("xiaoxiao")
    await plugin.engine.synthesize("a", "你好", role, "日语")
    assert provider.synthesize.call_args.args[0] == "こんにちは。"
    role.japanese_voice = "zh-CN-XiaoxiaoNeural"
    with pytest.raises(VoiceError, match="语言"):
        await plugin.engine.synthesize("a", "你好", role, "日语")


@pytest.mark.asyncio
async def test_timeout_and_bounded_concurrency(plugin):
    object.__setattr__(plugin.config.plugin, "timeout", 0.03)  # Accelerate the real timeout path in tests.
    provider = plugin.engine.providers["edge"]
    async def slow(*args):
        await asyncio.sleep(1)
    provider.synthesize = slow
    role = plugin.roles.find("xiaoxiao")
    tasks = [asyncio.create_task(plugin.engine.synthesize(s, "你好", role)) for s in ["a", "b"]]
    await asyncio.sleep(0)
    with pytest.raises(VoiceError, match="繁忙"):
        await plugin.engine.synthesize("c", "你好", role)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, VoiceError) and "超时" in str(r) for r in results)
    assert not plugin.engine.busy


@pytest.mark.asyncio
async def test_unload_cancels_work(plugin):
    started = asyncio.Event()
    async def slow(*args):
        started.set()
        await asyncio.sleep(10)
    plugin.engine.providers["edge"].synthesize = slow
    task = asyncio.create_task(plugin.engine.synthesize("s", "你好", plugin.roles.find("xiaoxiao")))
    await started.wait()
    await plugin.engine.close()
    assert task.cancelled()


@pytest.mark.parametrize("text", ["x" * 201, "```python\nprint(1)\n```", "https://example.com", ""])
def test_unreadable(plugin, text):
    assert not plugin.engine.readable(text)


@pytest.mark.parametrize("data,fmt", [(b"", "mp3"), (b"not audio", "wav"), (b"html", "mp3")])
def test_invalid_audio(data, fmt):
    with pytest.raises(VoiceError):
        checked_audio(data, fmt, "test")


@pytest.mark.parametrize("relative", ["../secret", "/etc/passwd", "..\\secret", ""])
def test_paths(tmp_path, relative):
    with pytest.raises(ValueError):
        safe_file(tmp_path, relative)


def test_symlink_rejected(tmp_path):
    (tmp_path / "file").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "file")
    with pytest.raises(ValueError):
        safe_file(tmp_path, "link")


def test_templates_pack_import_export_and_no_secrets(plugin, wav):
    assert plugin.roles.local_status(plugin.roles.find("xingnai")).startswith("未就绪")
    folder = plugin.state.root / "imports" / "test"
    folder.mkdir()
    (folder / "voice.wav").write_bytes(wav)
    pack = {"version": 1, "role": {"id": "star", "name": "星", "backend": "index", "reference": "voice.wav", "source": "自制"},
            "emotions": [{"name": "日常"}], "token": "must-not-export"}
    (folder / "role.json").write_text(json.dumps(pack))
    role = plugin.roles.import_pack("test")
    assert "配置就绪" in plugin.roles.local_status(role)
    exported = plugin.roles.export_pack(role)
    assert "must-not-export" not in (exported / "role.json").read_text()
    assert role.source == "自制"
    old = role.reference
    (folder / "voice.wav").write_bytes(wav + b"\x00\x00")
    assert plugin.roles.import_pack("test").reference != old


def test_failed_import_no_registry_change(plugin):
    folder = plugin.state.root / "imports" / "bad"
    folder.mkdir()
    (folder / "role.json").write_text(json.dumps({"version": 1, "role": {"id": "bad", "backend": "index", "reference": "../secret", "source": "test"}}))
    with pytest.raises(ValueError):
        plugin.roles.import_pack("bad")
    assert "bad" not in plugin.roles.packs


def test_atomic_restore_and_unknown_version(tmp_path):
    state = State(tmp_path)
    state.update("s", mode="持续", next=True)
    assert State(tmp_path).get("s")["next"]
    (tmp_path / "state.json").write_text('{"version":999,"sessions":{}}')
    with pytest.raises(ValueError):
        State(tmp_path)


def test_emotion_validation_fallback_and_remote_config(plugin):
    with pytest.raises(ValueError):
        Emotion(vector=[1])
    assert plugin.roles.emotion(plugin.roles.find("xingnai"), "invented").name == "日常"
    with pytest.raises(ValueError):
        IndexProvider(IndexSettings(url="http://example.com"), plugin.state.root)
