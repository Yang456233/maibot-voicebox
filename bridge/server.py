import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import hmac
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Literal
import wave

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

LIMIT = 20 * 1024 * 1024
RESOURCE = r"^[a-f0-9]{64}$"


class BodyLimit:
    """Bound the bytes before the multipart parser spools an upload to disk."""
    def __init__(self, app, token=""):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if self.token and not hmac.compare_digest(headers.get(b"authorization", b""), ("Bearer " + self.token).encode()):
            return await Response(status_code=401)(scope, receive, send)
        limit = LIMIT + 65536 if scope.get("path") == "/v1/references" else 16384
        chunks, size = [], 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            size += len(event.get("body", b""))
            if size > limit:
                return await Response(status_code=413)(scope, receive, send)
            chunks.append(event.get("body", b""))
            if not event.get("more_body", False):
                break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()
        await self.app(scope, bounded_receive, send)


@dataclass
class Settings:
    root: Path
    model_dir: Path
    token: str = ""
    host: str = "127.0.0.1"
    device: str = "auto"
    queue_size: int = 2
    request_timeout: float = 40
    model_revision: str = "IndexTTS-2.5-v2.5.0"
    max_references: int = 256

    @classmethod
    def environment(cls):
        return cls(root=Path(os.getenv("VOICEBOX_DATA", "./voicebox-service-data")),
            model_dir=Path(os.getenv("INDEX_MODEL_DIR", "./checkpoints")),
            token=os.getenv("VOICEBOX_TOKEN", ""), host=os.getenv("VOICEBOX_HOST", "127.0.0.1"),
            device=os.getenv("INDEX_DEVICE", "auto"),
            model_revision=os.getenv("INDEX_MODEL_REVISION", "IndexTTS-2.5-v2.5.0"))


class Synthesis(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    language: Literal["zh", "ja", "en"] = "zh"
    reference_id: str = Field(pattern=RESOURCE)
    emotion_reference_id: str | None = Field(default=None, pattern=RESOURCE)
    emotion_vector: list[float] | None = None
    emotion_strength: float = Field(default=0.6, ge=0, le=1)
    duration_factor: float = Field(default=1, ge=0.5, le=2)

    @model_validator(mode="after")
    def check_emotion(self):
        if self.emotion_reference_id and self.emotion_vector is not None:
            raise ValueError("情绪音频和向量只能选一种")
        if self.emotion_vector is not None and (
            len(self.emotion_vector) != 8 or any(not 0 <= v <= 1 for v in self.emotion_vector)):
            raise ValueError("情绪向量需为 8 个 0～1 数值")
        if not self.text.strip():
            raise ValueError("文本不能为空")
        return self


class IndexModel:
    def __init__(self, settings):
        from indextts.infer_v2_5 import IndexTTS2
        self.model = IndexTTS2(cfg_path=str(settings.model_dir / "config.yaml"),
            model_dir=str(settings.model_dir), device=None if settings.device == "auto" else settings.device,
            use_bf16=False, use_cuda_kernel=False)

    def synthesize(self, body, references, output):
        kwargs = {"spk_audio_prompt": str(references / (body.reference_id + ".wav")),
            "text": body.text, "output_path": str(output), "lang": body.language.upper(),
            "duration_factor": body.duration_factor, "use_random": False, "emo_alpha": body.emotion_strength}
        if body.emotion_reference_id:
            kwargs["emo_audio_prompt"] = str(references / (body.emotion_reference_id + ".wav"))
        elif body.emotion_vector is not None:
            kwargs["emo_vector"] = body.emotion_vector
        self.model.infer(**kwargs)
        return output.read_bytes()


def normalize_audio(data):
    """Decode to bounded PCM; file suffix alone is never accepted as proof of audio."""
    try:
        with wave.open(io.BytesIO(data)) as source:
            if source.getcomptype() != "NONE" or not 1 <= source.getnchannels() <= 2:
                raise ValueError("需要单声道或双声道 PCM 音频")
            duration = source.getnframes() / source.getframerate()
            if not 0.5 <= duration <= 30:
                raise ValueError("参考音频时长须为 0.5～30 秒")
            if len(source.readframes(source.getnframes())) != source.getnframes() * source.getnchannels() * source.getsampwidth():
                raise ValueError("音频数据不完整")
            return data
    except (wave.Error, EOFError):
        with tempfile.TemporaryDirectory(prefix="voicebox-audio-") as tmp:
            source, out = Path(tmp) / "input", Path(tmp) / "output.wav"
            source.write_bytes(data)
            try:
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-t", "31",
                    "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(out)],
                    check=True, timeout=10, capture_output=True)
            except (FileNotFoundError, subprocess.SubprocessError):
                raise ValueError("音频无法解码；MP3 需要服务端安装 FFmpeg") from None
            return normalize_audio(out.read_bytes())


def create_app(settings=None, model_factory=IndexModel):
    settings = settings or Settings.environment()
    if settings.host not in {"127.0.0.1", "localhost", "::1"} and not settings.token:
        raise ValueError("对外监听必须配置 VOICEBOX_TOKEN，并通过 HTTPS 反向代理访问")
    if settings.queue_size < 1:
        raise ValueError("queue_size 必须大于零")
    refs = settings.root / "references"
    refs.mkdir(parents=True, exist_ok=True)
    queue = asyncio.Queue(maxsize=settings.queue_size)
    status = {"ready": False, "message": "模型加载中"}
    model = None
    upload_lock = asyncio.Lock()

    async def worker():
        nonlocal model
        started = time.monotonic()
        try:
            model = await asyncio.to_thread(model_factory, settings)
            status.update(ready=True, message="模型已加载", load_seconds=round(time.monotonic() - started, 3))
        except Exception:
            status.update(ready=False, message="模型加载失败，请检查服务日志")
            logging.getLogger("voicebox.bridge").exception("模型加载失败")
            return
        while True:
            job = await queue.get()
            if job is None:
                queue.task_done()
                break
            body, future, deadline = job
            try:
                if future.cancelled() or time.monotonic() > deadline:
                    if not future.done():
                        future.set_exception(TimeoutError())
                    continue
                # One worker awaits the actual thread, including after client timeout.
                # Cancelling an HTTP request must never start overlapping model inference.
                with tempfile.TemporaryDirectory(prefix="voicebox-output-") as tmp:
                    data = await asyncio.to_thread(model.synthesize, body, refs, Path(tmp) / "speech.wav")
                if not data or not data.startswith(b"RIFF") or len(data) > 12 * 1024 * 1024:
                    raise ValueError("模型返回无效音频")
                if not future.done():
                    future.set_result(data)
            except Exception:
                logging.getLogger("voicebox.bridge").exception("模型合成失败")
                if not future.done():
                    future.set_exception(ValueError("模型合成失败"))
            finally:
                queue.task_done()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(worker())
        app.state.worker = task
        try:
            yield
        finally:
            status["ready"] = False
            while not queue.empty():
                item = queue.get_nowait()
                if item and not item[1].done():
                    item[1].cancel()
                queue.task_done()
            if not task.done():
                await queue.put(None)
                await task

    app = FastAPI(title="麦麦声匣 IndexTTS 桥接", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodyLimit, token=settings.token)

    async def auth(authorization: str = Header(default="")):
        if settings.token and not hmac.compare_digest(authorization, "Bearer " + settings.token):
            raise HTTPException(401, "服务密钥错误")

    @app.get("/", dependencies=[Depends(auth)])
    async def index():
        return {"service": "麦麦声匣 IndexTTS 2.5 桥接", "ready": status["ready"],
                "message": status["message"], "health": "/v1/health",
                "note": "声音角色请在麦麦 WebUI 的声匣插件配置中设置"}

    @app.get("/v1/health", dependencies=[Depends(auth)])
    async def health():
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_mb = rss / (1024**2 if sys.platform == "darwin" else 1024)
        except ImportError:
            rss_mb = None
        return {"api_version": 1, "engine": "indextts-2.5", "model_revision": settings.model_revision,
                **status, "queue_size": queue.qsize(), "peak_rss_mb": rss_mb, "requested_device": settings.device}

    @app.get("/v1/capabilities", dependencies=[Depends(auth)])
    async def capabilities():
        return {"languages": ["zh", "en", "ja"], "emotion_vector_order":
                ["happy", "angry", "sad", "afraid", "disgusted", "melancholic", "surprised", "calm"],
                "reference_max_seconds": 30, "reference_max_bytes": LIMIT}

    @app.post("/v1/references", dependencies=[Depends(auth)])
    async def upload(file: UploadFile = File(...)):
        data = await file.read(LIMIT + 1)
        await file.close()
        if len(data) > LIMIT:
            raise HTTPException(413, "参考音频最大 20MB")
        async with upload_lock:
            try:
                data = await asyncio.to_thread(normalize_audio, data)
            except (ValueError, ZeroDivisionError) as exc:
                raise HTTPException(422, str(exc)) from None
            resource = hashlib.sha256(data).hexdigest()
            path = refs / (resource + ".wav")
            if not path.exists():
                if len(list(refs.glob("*.wav"))) >= settings.max_references:
                    raise HTTPException(507, "参考音频存储已满，请管理员清理")
                fd, tmp = tempfile.mkstemp(dir=refs)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            return {"resource_id": resource, "fingerprint": resource}

    @app.post("/v1/synthesize", dependencies=[Depends(auth)])
    async def synthesize(body: Synthesis):
        if not status["ready"]:
            raise HTTPException(503, status["message"])
        for resource in (body.reference_id, body.emotion_reference_id):
            if resource and not (refs / (resource + ".wav")).is_file():
                raise HTTPException(404, "参考音频不存在，请重新上传")
        future = asyncio.get_running_loop().create_future()
        try:
            queue.put_nowait((body, future, time.monotonic() + settings.request_timeout))
        except asyncio.QueueFull:
            raise HTTPException(429, "合成队列已满") from None
        try:
            data = await asyncio.wait_for(asyncio.shield(future), settings.request_timeout)
            return Response(content=data, media_type="audio/wav")
        except (TimeoutError, asyncio.CancelledError):
            future.cancel()
            raise HTTPException(504, "合成超时") from None
        except ValueError:
            raise HTTPException(500, "模型合成失败，请检查服务日志") from None

    return app


def main():
    import uvicorn
    settings = Settings.environment()
    uvicorn.run(create_app(settings), host=settings.host, port=int(os.getenv("VOICEBOX_PORT", "7861")),
                limit_concurrency=16, timeout_keep_alive=5, access_log=False)


if __name__ == "__main__":
    main()
