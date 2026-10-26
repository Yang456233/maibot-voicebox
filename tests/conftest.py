import importlib.util
import io
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import wave

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("voicebox_plugin", ROOT / "plugin.py", submodule_search_locations=[str(ROOT)])
plugin_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin_module
spec.loader.exec_module(plugin_module)


@pytest.fixture
def wav():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x00" * 24000)
    return stream.getvalue()


@pytest_asyncio.fixture
async def plugin(tmp_path):
    p = plugin_module.create_plugin()
    p.set_plugin_config({"plugin": {"config_version": "0.1.0", "cooldown": 0}, "admin": {"qqs": ["42"]}})
    p._set_context(SimpleNamespace(paths=SimpleNamespace(data_dir=tmp_path), logger=logging.getLogger("test"),
        llm=SimpleNamespace(generate=AsyncMock(return_value={"success": True, "response": "こんにちは。"})),
        send=SimpleNamespace(text=AsyncMock(return_value={"sent": True}), custom=AsyncMock(return_value={"sent": True}))))
    await p.on_load()
    yield p
    await p.on_unload()
