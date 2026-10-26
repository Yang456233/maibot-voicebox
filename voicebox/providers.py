import asyncio
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
from urllib.parse import urlparse

import aiohttp

from .storage import audio_bytes, safe_file


class VoiceError(Exception):
    """A user-safe error; never include request headers or response bodies."""


@dataclass(frozen=True)
class Audio:
    content: bytes
    format: str
    model: str


def checked_audio(data, fmt, model):
    if not data or len(data) > 12 * 1024 * 1024:
        raise VoiceError("合成服务返回空音频或音频过大")
    valid = (fmt == "wav" and data[:4] == b"RIFF" and data[8:12] == b"WAVE") or (
        fmt == "mp3" and (data[:3] == b"ID3" or len(data) > 1 and data[0] == 255 and data[1] & 224 == 224))
    if not valid:
        raise VoiceError("合成服务返回的音频格式不正确")
    return Audio(data, fmt, model)


class EdgeProvider:
    def __init__(self, config):
        self.config = config
        self.revision = "edge-tts-" + version("edge-tts")

    def capabilities(self):
        return {"languages": ["zh", "ja", "en"], "controls": ["voice", "rate", "pitch", "volume"],
                "cloning": False, "emotion": False}

    async def health(self):
        try:
            import edge_tts
            voices = await asyncio.wait_for(edge_tts.list_voices(proxy=self.config.proxy or None), 8)
            return {"ready": bool(voices), "message": "Edge 可连接（音色目录检查）", "model": self.revision}
        except Exception:
            return {"ready": False, "message": "Edge 不可连接，请检查网络或代理", "model": self.revision}

    async def synthesize(self, text, role, language, emotion):
        import edge_tts
        voice = role.japanese_voice if language == "ja" else role.voice
        if not voice.lower().startswith(language + "-"):
            raise VoiceError("Edge 音色与朗读语言不匹配")
        for attempt in range(self.config.retries + 1):
            try:
                stream = edge_tts.Communicate(text, voice, rate=f"{role.rate:+d}%",
                    pitch=f"{role.pitch:+d}Hz", volume=f"{role.volume:+d}%",
                    proxy=self.config.proxy or None, connect_timeout=5, receive_timeout=15)
                chunks, size = [], 0
                async for item in stream.stream():
                    if item["type"] == "audio":
                        size += len(item["data"])
                        if size > 12 * 1024 * 1024:
                            raise VoiceError("音频过大")
                        chunks.append(item["data"])
                return checked_audio(b"".join(chunks), "mp3", self.revision)
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == self.config.retries:
                    raise VoiceError("Edge 合成失败，请检查网络与音色 ID") from None
                await asyncio.sleep(0.25)

    async def close(self):
        pass


class IndexProvider:
    def __init__(self, config, assets):
        self.config, self.assets = config, assets
        parsed = urlparse(config.url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("IndexTTS 地址应为不含密码的 HTTP(S) 地址")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and (
            parsed.scheme != "https" or not config.token):
            raise ValueError("远程 IndexTTS 必须使用 HTTPS 和服务密钥")
        self.session = None
        self.revision = "unknown"

    def capabilities(self):
        return {"languages": ["zh", "ja", "en"], "controls": ["reference", "emotion", "duration_factor"],
                "cloning": True, "emotion": True}

    async def client(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=50),
                headers={"Authorization": "Bearer " + self.config.token} if self.config.token else {})
        return self.session

    async def request(self, path, **kwargs):
        client = await self.client()
        method = kwargs.pop("method", "GET")
        async with client.request(method, self.config.url.rstrip("/") + "/v1/" + path,
                                  allow_redirects=False, **kwargs) as response:
            if response.status >= 300:
                raise VoiceError(f"IndexTTS 服务请求失败（HTTP {response.status}）")
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > 12 * 1024 * 1024:
                    raise VoiceError("服务响应过大")
                chunks.append(chunk)
            data = b"".join(chunks)
            if path == "synthesize":
                return data
            import json
            return json.loads(data)

    async def health(self):
        try:
            result = await asyncio.wait_for(self.request("health"), 5)
            if result.get("api_version") != 1 or result.get("engine") != "indextts-2.5":
                raise VoiceError("桥接服务版本不匹配")
            self.revision = str(result.get("model_revision", "unknown"))
            return {"ready": bool(result.get("ready")), "message": str(result.get("message", ""))[:100],
                    "model": self.revision}
        except Exception:
            return {"ready": False, "message": "IndexTTS 未连接或模型尚未加载", "model": self.revision}

    def fingerprint(self, relative):
        if not relative:
            return ""
        return hashlib.sha256(audio_bytes(safe_file(self.assets, relative))).hexdigest()

    async def upload(self, relative):
        path = safe_file(self.assets, relative)
        data = aiohttp.FormData()
        data.add_field("file", audio_bytes(path), filename="reference" + path.suffix.lower(),
                       content_type="application/octet-stream")
        result = await self.request("references", method="POST", data=data)
        return result["resource_id"]

    async def synthesize(self, text, role, language, emotion):
        body = {"text": text, "language": language, "reference_id": await self.upload(role.reference),
                "emotion_strength": emotion.strength, "duration_factor": role.duration_factor}
        if emotion.reference:
            body["emotion_reference_id"] = await self.upload(emotion.reference)
        elif any(emotion.vector):
            body["emotion_vector"] = emotion.vector
        data = await self.request("synthesize", method="POST", json=body)
        return checked_audio(data, "wav", self.revision)

    async def close(self):
        if self.session:
            await self.session.close()
