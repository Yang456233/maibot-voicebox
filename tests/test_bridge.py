import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from bridge.server import create_app, Settings, Synthesis


async def ready(client):
    for _ in range(100):
        if (await client.get("/v1/health")).json()["ready"]:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("Fake model failed to load")


@pytest.mark.asyncio
async def test_upload_synthesize_auth_and_missing_reference(tmp_path, wav):
    calls = []
    def synth(body, refs, output):
        calls.append(body)
        return wav
    app = create_app(Settings(tmp_path, tmp_path, token="test-only"), lambda _: SimpleNamespace(synthesize=synth))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/v1/health")).status_code == 401
        assert (await client.get("/")).status_code == 401
        client.headers["Authorization"] = "Bearer test-only"
        await ready(client)
        assert (await client.get("/")).json()["ready"] is True
        result = await client.post("/v1/references", files={"file": ("../../evil.wav", wav)})
        assert result.status_code == 200
        resource = result.json()["resource_id"]
        result = await client.post("/v1/synthesize", json={"text": "こんにちは", "language": "ja", "reference_id": resource,
            "emotion_vector": [1, 0, 0, 0, 0, 0, 0, 0]})
        assert result.status_code == 200 and result.content == wav and len(calls) == 1
        result = await client.post("/v1/synthesize", json={"text": "你好", "reference_id": "0" * 64})
        assert result.status_code == 404
        assert (await client.get("/v1/capabilities")).json()["languages"] == ["zh", "en", "ja"]


@pytest.mark.asyncio
async def test_timeout_keeps_actual_inference_serial_and_bounds_queue(tmp_path, wav):
    active, maximum, calls = 0, 0, 0
    def slow(*args):
        nonlocal active, maximum, calls
        active += 1
        calls += 1
        maximum = max(active, maximum)
        time.sleep(0.15)
        active -= 1
        return wav
    app = create_app(Settings(tmp_path, tmp_path, queue_size=1, request_timeout=0.04), lambda _: SimpleNamespace(synthesize=slow))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await ready(client)
        ref = (await client.post("/v1/references", files={"file": ("a.wav", wav)})).json()["resource_id"]
        payload = {"text": "你好", "reference_id": ref}
        first = asyncio.create_task(client.post("/v1/synthesize", json=payload))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(client.post("/v1/synthesize", json=payload))
        await asyncio.sleep(0.01)
        assert (await client.post("/v1/synthesize", json=payload)).status_code == 429
        assert [r.status_code for r in await asyncio.gather(first, second)] == [504, 504]
    assert maximum == 1 and calls == 1


@pytest.mark.asyncio
async def test_model_load_failure_is_not_healthy(tmp_path):
    def broken(_):
        raise RuntimeError("missing model")
    app = create_app(Settings(tmp_path, tmp_path), broken)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await asyncio.sleep(0.01)
        assert not (await client.get("/v1/health")).json()["ready"]
        assert (await client.get("/")).json()["ready"] is False
        assert (await client.post("/v1/synthesize", json={"text": "你好", "reference_id": "0" * 64})).status_code == 503


@pytest.mark.parametrize("body", [{"reference_id": "../secret"}, {"emotion_vector": [2] * 8}, {"emotion_vector": [0] * 8, "emotion_reference_id": "0" * 64}])
def test_synthesis_validation(body):
    with pytest.raises(ValueError):
        Synthesis.model_validate({"text": "hello", "reference_id": "0" * 64, **body})


def test_remote_requires_token(tmp_path):
    with pytest.raises(ValueError):
        create_app(Settings(tmp_path, tmp_path, host="0.0.0.0"))
