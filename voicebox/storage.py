"""Atomic session state and deliberately non-executable role packs."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .config import Role, Emotion

MAX_AUDIO = 20 * 1024 * 1024


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".voicebox-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def safe_file(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative or Path(relative).is_absolute():
        raise ValueError("资源必须使用目录内的相对路径")
    parts = Path(relative).parts
    if ".." in parts:
        raise ValueError("不允许上级目录")
    path = root.joinpath(relative)
    for i in range(1, len(parts) + 1):
        if root.joinpath(*parts[:i]).is_symlink():
            raise ValueError("不接受符号链接资源")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("资源不存在或越过资源目录")
    return path


def audio_bytes(path: Path) -> bytes:
    if path.suffix.lower() not in {".wav", ".mp3"} or not 32 <= path.stat().st_size <= MAX_AUDIO:
        raise ValueError("参考音频需为 WAV/MP3，大小 32 字节～20MB")
    data = path.read_bytes()
    if not (data.startswith(b"RIFF") and data[8:12] == b"WAVE" or data.startswith(b"ID3")
            or data[0] == 255 and data[1] & 224 == 224):
        raise ValueError("音频文件头无效")
    return data


class State:
    def __init__(self, root: Path):
        self.root = root
        for name in ("assets", "imports", "exports"):
            (root / name).mkdir(parents=True, exist_ok=True)
        self.path = root / "state.json"
        self.sessions = {}
        if self.path.exists():
            data = json.loads(self.path.read_text())
            if data.get("version") != 1 or not isinstance(data.get("sessions"), dict):
                raise ValueError("会话文件版本不兼容，请保留文件后检查升级说明")
            self.sessions = data["sessions"]

    def get(self, session):
        raw = self.sessions.get(session, {})
        return {"role": raw.get("role", ""), "mode": raw.get("mode", "自动"),
                "language": raw.get("language", "原文"), "next": bool(raw.get("next", False))}

    def update(self, session, **changes):
        value = self.get(session)
        value.update(changes)
        new = dict(self.sessions)
        new[session] = value
        atomic_json(self.path, {"version": 1, "sessions": new})
        self.sessions = new


class Roles:
    def __init__(self, state: State, config):
        self.state, self.config = state, config
        self.pack_path = state.root / "roles.json"
        self.packs = json.loads(self.pack_path.read_text()) if self.pack_path.exists() else {}
        for pack in self.packs.values():
            Role.model_validate(pack["role"])
            for preset in pack["emotions"]:
                Emotion.model_validate(preset)

    def all(self):
        result = {r.id: r for r in self.config.roles.items}
        result.update({k: Role.model_validate(v["role"]) for k, v in self.packs.items()})
        return list(result.values())

    def find(self, name):
        matches = [r for r in self.all() if name in (r.id, r.name)]
        if len(matches) != 1:
            raise ValueError("角色不存在或名称重复，请使用角色 ID")
        return matches[0]

    def emotion(self, role, name):
        presets = self.config.emotions.presets
        if role.id in self.packs:
            presets = [Emotion.model_validate(e) for e in self.packs[role.id]["emotions"]]
        selected = name if name in role.emotions else role.default_emotion
        return next((e for e in presets if e.name == selected), Emotion())

    def local_status(self, role):
        try:
            if role.backend == "index":
                audio_bytes(safe_file(self.state.root / "assets", role.reference))
            elif not role.voice:
                return "未就绪：缺少 Edge 音色"
            return "配置就绪（服务以状态检查为准）"
        except ValueError:
            return "未就绪：缺少有效参考音频"

    def import_pack(self, name):
        if not re.fullmatch(r"[\w-]{1,64}", name):
            raise ValueError("包名只能包含文字、数字、下划线和短横线")
        folder = self.state.root / "imports" / name
        manifest = safe_file(self.state.root / "imports", f"{name}/role.json")
        if manifest.stat().st_size > 128 * 1024:
            raise ValueError("角色清单过大")
        pack = json.loads(manifest.read_text())
        if pack.get("version") != 1:
            raise ValueError("只支持版本 1 角色包")
        role = Role.model_validate(pack["role"])
        emotions = [Emotion.model_validate(e) for e in pack.get("emotions", [{"name": "日常"}])]
        if len({e.name for e in emotions}) != len(emotions):
            raise ValueError("语气名称重复")
        if role.backend == "index" and (not role.reference or not role.source.strip()):
            raise ValueError("IndexTTS 角色需要参考音频和素材来源说明")
        if not set(role.emotions + [role.default_emotion]).issubset({e.name for e in emotions}):
            raise ValueError("角色引用了未提供的语气")
        pending = []
        for item in [role, *emotions]:
            if not item.reference:
                continue
            source = safe_file(folder, item.reference)
            content = audio_bytes(source)
            filename = hashlib.sha256(content).hexdigest() + source.suffix.lower()
            pending.append((filename, content))
            item.reference = filename
        # Validate the complete pack before committing its registry record.
        for filename, content in pending:
            (self.state.root / "assets" / filename).write_bytes(content)
        packs = dict(self.packs)
        packs[role.id] = {"role": role.model_dump(), "emotions": [e.model_dump() for e in emotions]}
        atomic_json(self.pack_path, packs)
        self.packs = packs
        return role

    def export_pack(self, role):
        folder = self.state.root / "exports" / role.id
        folder.mkdir(exist_ok=True)
        role = role.model_copy(deep=True)
        emotions = [self.emotion(role, name).model_copy(deep=True) for name in role.emotions]
        for item in [role, *emotions]:
            if item.reference:
                path = safe_file(self.state.root / "assets", item.reference)
                data = audio_bytes(path)
                name = hashlib.sha256(data).hexdigest() + path.suffix.lower()
                (folder / name).write_bytes(data)
                item.reference = name
        atomic_json(folder / "role.json", {"version": 1, "role": role.model_dump(),
                                          "emotions": [e.model_dump() for e in emotions]})
        return folder
