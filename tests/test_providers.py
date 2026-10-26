import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from voicebox_plugin.voicebox.providers import VoiceError


@pytest.mark.asyncio
async def test_index_stream_reads_all_chunks(plugin, wav):
    provider = plugin.engine.providers["index"]
    async def chunks(size):
        yield wav[:80]
        yield wav[80:10000]
        yield wav[10000:]
    class Response:
        status = 200
        content = SimpleNamespace(iter_chunked=chunks)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    seen = []
    def request(*args, **kwargs):
        seen.append(kwargs)
        return Response()
    provider.client = AsyncMock(return_value=SimpleNamespace(request=request))
    assert await provider.request("synthesize", method="POST", json={}) == wav
    assert seen[0]["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"api_version": 2, "engine": "indextts-2.5", "ready": True},
    {"api_version": 1, "engine": "other", "ready": True},
    {"api_version": 1, "engine": "indextts-2.5", "ready": False}])
async def test_index_health_does_not_accept_wrong_service(plugin, result):
    provider = plugin.engine.providers["index"]
    provider.request = AsyncMock(return_value=result)
    assert not (await provider.health())["ready"]


@pytest.mark.asyncio
async def test_index_unavailable_and_empty_audio(plugin, wav):
    role = plugin.roles.find("xingnai")
    role.reference = "voice.wav"
    (plugin.state.root / "assets/voice.wav").write_bytes(wav)
    provider = plugin.engine.providers["index"]
    provider.health = AsyncMock(return_value={"ready": False, "message": "unavailable"})
    with pytest.raises(VoiceError, match="unavailable"):
        await plugin.engine.synthesize("s", "你好", role)
    provider.health.return_value = {"ready": True}
    provider.upload = AsyncMock(return_value="0" * 64)
    provider.request = AsyncMock(return_value=b"")
    with pytest.raises(VoiceError, match="空音频"):
        await plugin.engine.synthesize("s", "你好", role)


@pytest.mark.asyncio
async def test_edge_empty_audio_retries_are_bounded(plugin, monkeypatch):
    import edge_tts
    calls = []
    class Empty:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
        async def stream(self):
            yield {"type": "WordBoundary"}
    monkeypatch.setattr(edge_tts, "Communicate", Empty)
    with pytest.raises(VoiceError, match="Edge 合成失败"):
        await plugin.engine.synthesize("s", "你好", plugin.roles.find("xiaoxiao"))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cache_eviction_and_reference_fingerprint(plugin, wav):
    from voicebox_plugin.voicebox.providers import Audio
    plugin.config.plugin.cache_entries = 1
    edge = plugin.engine.providers["edge"]
    edge.synthesize = AsyncMock(return_value=Audio(wav, "wav", "test"))
    role = plugin.roles.find("xiaoxiao")
    for text in ["你好", "再见", "你好"]:
        await plugin.engine.synthesize("s", text, role)
    assert edge.synthesize.await_count == 3
    index = plugin.engine.providers["index"]
    (plugin.state.root / "assets/ref.wav").write_bytes(wav)
    first = index.fingerprint("ref.wav")
    (plugin.state.root / "assets/ref.wav").write_bytes(wav + b"data")
    assert index.fingerprint("ref.wav") != first
