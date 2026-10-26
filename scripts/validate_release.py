"""Offline release contract, SDK schema, examples and accidental secret checks."""
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {"_manifest.json", "plugin.py", "README.md", "LICENSE", "THIRD_PARTY.md", "CHANGELOG.md",
             "config.example.toml", "requirements.txt", "requirements-dev.txt", "pyproject.toml", ".gitignore"}
FOLDERS = {"voicebox", "bridge", "tests", "docs", "scripts", ".github"}


def release_files():
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if path.is_symlink() or not path.is_file() or "__pycache__" in relative.parts:
            continue
        if len(relative.parts) == 1 and relative.name in TOP_FILES or relative.parts[0] in FOLDERS and path.suffix in {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml"}:
            yield path


def validate():
    manifest = json.loads((ROOT / "_manifest.json").read_text())
    assert manifest["manifest_version"] == 2
    assert manifest["id"] == "github.Yang456233.maibot-voicebox"
    assert manifest["urls"]["repository"] == "https://github.com/Yang456233/maibot-voicebox"
    assert manifest["license"] == "MIT"
    for version in [manifest["version"], *manifest["host_application"].values(), *manifest["sdk"].values()]:
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
        assert not set(version.split(".")[:2]) & {"99", "999"}
    assert set(manifest["capabilities"]) == {"send.custom", "send.text", "llm.generate"}
    for required in TOP_FILES:
        assert (ROOT / required).is_file(), required
    spec = importlib.util.spec_from_file_location("voicebox_release", ROOT / "plugin.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    plugin = module.create_plugin()
    assert plugin.get_webui_config_schema()
    plugin.set_plugin_config(tomllib.loads((ROOT / "config.example.toml").read_text()))
    assert plugin.config.plugin.config_version == manifest["version"]
    for path in release_files():
        content = path.read_text(encoding="utf-8")
        assert not re.search(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN [A-Z ]*PRIVATE KEY-----", content), f"Potential secret: {path.name}"
        if path.suffix in {".json", ".toml"} and path.name != "_manifest.json":
            assert not re.search(r'(?:token|api_key|password)\s*[=:]\s*["\'][^"\']{16,}', content), f"Potential config secret: {path.name}"
    print(f"Validated {manifest['id']} {manifest['version']}: manifest contract, SDK config, example and secret patterns")
    return manifest


if __name__ == "__main__":
    validate()
