"""麦麦声匣 — SDK-only integration; the host owns reply sending/history."""
import asyncio
import base64
from collections import OrderedDict
from copy import deepcopy
import hashlib
from pathlib import Path
import re
import time

from maibot_sdk import (MaiBotPlugin, Command, ReplyExtension, HookHandler,
                        CONFIG_RELOAD_SCOPE_SELF)
from maibot_sdk.types import HookMode

from .voicebox.config import VoiceboxConfig
from .voicebox.engine import Engine
from .voicebox.providers import VoiceError
from .voicebox.storage import State, Roles

EXTENSION = "github.Yang456233.maibot-voicebox.voice"
SAMPLE = "今天也辛苦了。很高兴见到你，我们慢慢聊吧。"
HELP = """麦麦声匣
/声匣 状态｜角色｜帮助
/声匣 切换 <角色 ID>
/声匣 试听 <角色 ID> [语气]
/声匣 说 <文本>
/声匣 模式 自动|持续|文字
/声匣 下次语音
/声匣 语言 原文|日语
/声匣 导入 <包名>｜导出 <角色 ID>（管理员）
/声匣 清缓存（管理员）
群聊设置仅配置管理员可改。声音角色不改变麦麦人格。"""


def explicit_voice(text):
    return bool(re.search(r"(?:用|发|来|听|说|语音)(?:.{0,6})(?:语音|声音|朗读)|朗读.{0,8}(?:一下|出来)", text)) and not re.search(r"别|不要|不用|禁止", text)


def convert_messages(messages, original, encoded, keep_text=False):
    if any(s.get("type") == "voice" for m in messages for s in m.get("segments", [])):
        return None
    result, inserted = [], False
    for message in deepcopy(messages):
        segments = []
        for segment in message["segments"]:
            if segment.get("type") != "text":
                segments.append(segment)
                continue
            if not inserted:
                segments.append({"type": "voice", "data": original, "binary_data_base64": encoded})
                inserted = True
            if keep_text:
                segments.append(segment)
        if segments:
            result.append({"segments": segments, "quote_previous": message["quote_previous"]})
    return result if inserted else None


class VoiceboxPlugin(MaiBotPlugin):
    config_model = VoiceboxConfig

    async def on_load(self):
        self.state = State(Path(self.ctx.paths.data_dir))
        self.roles = Roles(self.state, self.config)
        self.engine = Engine(self.config, self.roles, self.ctx.llm)
        self.explicit = OrderedDict()
        self.seen = OrderedDict()
        self.pending = OrderedDict()
        self.sessions = OrderedDict()
        self.inflight = set()
        self.ctx.logger.info("麦麦声匣已加载；IndexTTS 模板需先导入参考音频")

    async def on_unload(self):
        if hasattr(self, "engine"):
            await self.engine.close()

    async def on_config_update(self, scope, config_data, version):
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            await self.on_unload()
            await self.on_load()

    def remember(self, mapping, key, value):
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > 1024:
            mapping.popitem(last=False)

    @HookHandler("chat.receive.before_process", mode=HookMode.OBSERVE, timeout_ms=1000)
    async def receive(self, message=None, **kwargs):
        if not message or message.get("platform") != "qq" or message.get("is_notify"):
            return
        session, mid = message.get("session_id"), str(message.get("message_id", ""))
        if not session:
            return
        self.remember(self.sessions, session, "qq")
        text = "".join(str(s.get("data", "")) for s in message.get("raw_message", []) if s.get("type") == "text")
        if not text.startswith("/") and explicit_voice(text) and mid:
            self.remember(self.explicit, (session, mid), time.monotonic())

    @HookHandler("maisaka.planner.after_response", mode=HookMode.BLOCKING, timeout_ms=1000)
    async def plan_reply(self, **kwargs):
        session = kwargs.get("session_id", "")
        if not self.config.plugin.enabled or self.sessions.get(session) != "qq":
            return
        setting = self.state.get(session)
        used_next = False
        for item in kwargs.get("output_items", []):
            call = item.get("tool_call") or {}
            if call.get("func_name") != "reply":
                continue
            args = call.get("args")
            if not isinstance(args, dict):
                continue
            options = args.setdefault("plugin_options", {})
            if not isinstance(options, dict):
                continue
            if setting["mode"] == "文字":
                options.pop(EXTENSION, None)
                continue
            mid = str(args.get("msg_id", ""))
            explicit = time.monotonic() - self.explicit.get((session, mid), -float("inf")) < 300
            once = setting["next"] and not used_next
            if setting["mode"] == "持续" or explicit or once:
                options.setdefault(EXTENSION, {"emotion": ""})
                used_next = used_next or once
        return {"action": "continue", "modified_kwargs": kwargs}

    @HookHandler("maisaka.planner.before_request", mode=HookMode.BLOCKING, timeout_ms=1000)
    async def describe_voice(self, **kwargs):
        session = kwargs.get("session_id", "")
        setting = self.state.get(session)
        try:
            role = self.roles.find(setting["role"] or self.config.plugin.default_role)
        except ValueError:
            role = None
        for tool in kwargs.get("tool_definitions", []):
            function = tool.get("function", {})
            if function.get("name") != "reply":
                continue
            props = function.get("parameters", {}).get("properties", {})
            extensions = props.get("plugin_options", {}).get("properties", {})
            if EXTENSION not in extensions:
                continue
            if not self.config.plugin.enabled or setting["mode"] == "文字" or role is None:
                extensions.pop(EXTENSION, None)
                continue
            schema = extensions[EXTENSION]
            schema["properties"]["emotion"]["enum"] = [""] + (role.emotions if role.backend == "index" else [])
            schema["description"] += f" 当前声音：{role.name}；朗读语言模式：{setting['language']}。"
        return {"action": "continue", "modified_kwargs": kwargs}

    @ReplyExtension("voice", platforms="qq", timeout_ms=60000,
        description="需要语音、朗读或适合亲切的短语音回复时选择。只转换当前回复，不改变人格。emotion 只能是已配置语气，不确定时留空；Edge 不支持情绪克隆。",
        parameters={"type": "object", "properties": {"emotion": {"type": "string", "maxLength": 30}},
                    "additionalProperties": False})
    async def voice_reply(self, phase="", session_id="", reply_id="", call_id="", parameters=None,
                          text="", messages=None, chat=None, reply_message_id="", **kwargs):
        if phase != "before_send" or not self.config.plugin.enabled or (chat or {}).get("platform") != "qq":
            return {}
        setting = self.state.get(session_id)
        if setting["mode"] == "文字" or not reply_id or not session_id:
            return {}
        key = (session_id, call_id or reply_id)
        if key in self.seen or session_id in self.inflight:
            return {}
        messages = messages or []
        if any(s.get("type") == "voice" for m in messages for s in m.get("segments", [])):
            return {}
        original = "\n".join("".join(s.get("data", "") for s in m.get("segments", [])
            if s.get("type") == "text") for m in messages).strip()
        if not self.engine.readable(original):
            return {}
        self.remember(self.seen, key, True)
        self.inflight.add(session_id)
        try:
            if setting["next"]:
                self.state.update(session_id, next=False)
            self.explicit.pop((session_id, str(reply_message_id)), None)
            role = self.roles.find(setting["role"] or self.config.plugin.default_role)
            audio = await self.engine.synthesize(session_id, original, role, setting["language"],
                                                 (parameters or {}).get("emotion", ""))
            encoded = base64.b64encode(audio.content).decode()
            keep = setting["language"] == "日语" and self.config.translation.keep_chinese
            converted = convert_messages(messages, original, encoded, keep)
            if not converted:
                return {}
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            self.remember(self.pending, (session_id, digest), (time.monotonic(), original, keep))
            return {"messages": converted}
        except asyncio.CancelledError:
            return {}
        except Exception as exc:
            # Do not propagate exceptions: the host otherwise aborts the entire reply.
            self.ctx.logger.warning("声匣保留文字：%s", str(exc) if isinstance(exc, VoiceError) else type(exc).__name__)
            return {}
        finally:
            self.inflight.discard(session_id)

    @HookHandler("send_service.after_send", mode=HookMode.OBSERVE, timeout_ms=5000)
    async def after_send(self, message=None, sent=None, **kwargs):
        if not message:
            return
        session = message.get("session_id", "")
        for segment in message.get("raw_message", []):
            if segment.get("type") != "voice":
                continue
            encoded = segment.get("binary_data_base64", "")
            key = (session, hashlib.sha256(encoded.encode()).hexdigest())
            pending = self.pending.pop(key, None)
            if not pending or time.monotonic() - pending[0] > 120:
                continue
            # Host stops the reply batch on a definite failure, including the
            # Japanese voice+original-text message. Restore the original once.
            if sent is False:
                try:
                    await self.ctx.send.text(pending[1], session, return_details=True)
                except Exception:
                    self.ctx.logger.warning("文字回退发送状态未知，不再补发")

    async def command_audio(self, session, text, role, language, emotion):
        try:
            audio = await self.engine.synthesize(session, text, role, language, emotion)
        except VoiceError as exc:
            await self.ctx.send.text(f"{exc}\n{text}", session)
            return
        encoded = base64.b64encode(audio.content).decode()
        try:
            result = await self.ctx.send.custom("voice", encoded, session, processed_plain_text=text, return_details=True)
        except Exception:
            self.ctx.logger.warning("语音发送状态未知，不重发")
            return
        failed = result is False or isinstance(result, dict) and result.get("sent") is False
        if failed or language == "日语" and self.config.translation.keep_chinese:
            await self.ctx.send.text(text, session)

    @Command("voicebox", description="角色语音控制", pattern=r"^/声匣(?:\s+(?P<args>[\s\S]*))?$", timeout_ms=60000)
    async def command(self, stream_id="", user_id="", group_id="", platform="", matched_groups=None, **kwargs):
        if not stream_id or platform != "qq":
            return False, "声匣首版仅支持 QQ。", True
        words = str((matched_groups or {}).get("args") or "帮助").strip().split(maxsplit=1)
        action, rest = (words[0], words[1] if len(words) > 1 else "") if words else ("帮助", "")
        admin = str(user_id) in self.config.admin.qqs
        mutating = action in {"切换", "模式", "下次语音", "语言"}
        if (mutating and group_id and not admin) or (action in {"导入", "导出", "清缓存"} and not admin):
            await self.ctx.send.text("此操作仅配置的管理员可用。", stream_id)
            return True, None, True
        self.remember(self.sessions, stream_id, "qq")
        setting = self.state.get(stream_id)
        try:
            if action == "帮助":
                answer = HELP
            elif action == "角色":
                answer = "\n".join(f"{r.id} · {r.name} [{r.backend}] {self.roles.local_status(r)}" for r in self.roles.all())
            elif action == "状态":
                statuses = await asyncio.gather(*(p.health() for p in self.engine.providers.values()))
                answer = f"角色：{setting['role'] or self.config.plugin.default_role}\n模式：{setting['mode']}\n语言：{setting['language']}\n下次语音：{setting['next']}\n" + "\n".join(s["message"] for s in statuses)
            elif action == "切换":
                role = self.roles.find(rest)
                if self.roles.local_status(role).startswith("未就绪"):
                    raise ValueError("角色未就绪，请先导入参考音频")
                self.state.update(stream_id, role=role.id)
                answer = f"当前会话声音已切换为 {role.name}。"
            elif action == "模式" and rest in {"自动", "持续", "文字"}:
                self.state.update(stream_id, mode=rest, next=False)
                answer = f"当前会话已设为{rest}模式。"
            elif action == "语言" and rest in {"原文", "日语"}:
                self.state.update(stream_id, language=rest)
                answer = f"当前会话朗读语言：{rest}。"
            elif action == "下次语音":
                if setting["mode"] == "文字":
                    raise ValueError("请先切换到自动或持续模式")
                self.state.update(stream_id, next=True)
                answer = "下一次适合朗读的普通回复将尝试使用语音。"
            elif action in {"试听", "说"}:
                if not rest:
                    raise ValueError("请提供角色 ID 或待朗读文本")
                parts = rest.split(maxsplit=1)
                role = self.roles.find(parts[0] if action == "试听" else setting["role"] or self.config.plugin.default_role)
                await self.command_audio(stream_id, SAMPLE if action == "试听" else rest, role,
                    setting["language"], parts[1] if action == "试听" and len(parts) > 1 else "")
                return True, None, True
            elif action == "导入":
                role = self.roles.import_pack(rest)
                self.engine.clear()
                answer = f"已导入 {role.name}（{role.id}）。使用 /声匣 试听 {role.id} 检查。"
            elif action == "导出":
                folder = self.roles.export_pack(self.roles.find(rest))
                answer = f"已导出至插件数据目录 exports/{folder.name}，仅包含角色、语气与音频。"
            elif action == "清缓存":
                self.engine.clear()
                answer = "合成缓存已清除。"
            else:
                answer = HELP
        except (ValueError, OSError) as exc:
            answer = f"操作未完成：{exc}"
        await self.ctx.send.text(answer, stream_id)
        return True, None, True


def create_plugin():
    return VoiceboxPlugin()
