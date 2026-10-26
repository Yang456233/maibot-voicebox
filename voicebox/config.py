from typing import ClassVar, Literal
from maibot_sdk import Field, PluginConfigBase
from pydantic import model_validator


def ui(label, **extra):
    return {"label": label, **extra}


class PluginSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "插件与行为"
    enabled: bool = Field(default=True, json_schema_extra=ui("启用声匣"))
    config_version: str = Field(default="0.1.0", json_schema_extra=ui("配置版本", hidden=True))
    default_role: str = Field(default="xiaoxiao", json_schema_extra=ui("默认角色 ID"))
    max_text_length: int = Field(default=200, ge=10, le=500, json_schema_extra=ui("语音最大字数"))
    timeout: float = Field(default=45, ge=5, le=50, json_schema_extra=ui("含排队与翻译的总超时（秒）"))
    cooldown: float = Field(default=3, ge=0, le=60, json_schema_extra=ui("每会话语音间隔（秒）"))
    cache_entries: int = Field(default=32, ge=0, le=128, json_schema_extra=ui("音频缓存条数"))
    cache_mb: int = Field(default=32, ge=1, le=128, json_schema_extra=ui("缓存容量（MB）"))


class EdgeSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "Edge 服务"
    proxy: str = Field(default="", json_schema_extra=ui("代理地址（可留空）"))
    retries: int = Field(default=1, ge=0, le=2, json_schema_extra=ui("合成重试次数"))


class IndexSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "IndexTTS 服务"
    url: str = Field(default="http://127.0.0.1:7861", json_schema_extra=ui("声匣桥接服务地址"))
    token: str = Field(default="", json_schema_extra=ui("服务密钥", input_type="password"))


class Emotion(PluginConfigBase):
    name: str = Field(default="日常", min_length=1, max_length=30, json_schema_extra=ui("语气名称"))
    vector: list[float] = Field(default_factory=lambda: [0, 0, 0, 0, 0, 0, 0, 0], json_schema_extra=ui("情绪向量", hint="8 项：开心、生气、悲伤、害怕、厌恶、低落、惊讶、平静；仅 IndexTTS"))
    reference: str = Field(default="", json_schema_extra=ui("情绪参考音频（资源目录内相对路径，可空）"))
    strength: float = Field(default=0.6, ge=0, le=1, json_schema_extra=ui("情绪强度"))

    @model_validator(mode="after")
    def validate_vector(self):
        if len(self.vector) != 8 or any(not 0 <= v <= 1 for v in self.vector):
            raise ValueError("情绪向量必须为 8 个 0～1 数值")
        return self


class Role(PluginConfigBase):
    id: str = Field(default="role", pattern=r"^[a-z][a-z0-9_-]{0,47}$", json_schema_extra=ui("角色 ID"))
    name: str = Field(default="角色", min_length=1, max_length=50, json_schema_extra=ui("角色名称"))
    backend: Literal["edge", "index"] = Field(default="edge", json_schema_extra=ui("语音引擎"))
    language: Literal["zh", "ja", "en"] = Field(default="zh", json_schema_extra=ui("原文默认语言"))
    voice: str = Field(default="zh-CN-XiaoxiaoNeural", json_schema_extra=ui("Edge 音色 ID"))
    japanese_voice: str = Field(default="ja-JP-NanamiNeural", json_schema_extra=ui("Edge 日语音色 ID"))
    reference: str = Field(default="", json_schema_extra=ui("IndexTTS 角色音频（资源目录内相对路径）"))
    rate: int = Field(default=0, ge=-50, le=100, json_schema_extra=ui("Edge 语速（%）"))
    pitch: int = Field(default=0, ge=-50, le=50, json_schema_extra=ui("Edge 音调（Hz）"))
    volume: int = Field(default=0, ge=-100, le=100, json_schema_extra=ui("Edge 音量（%）"))
    duration_factor: float = Field(default=1, ge=0.5, le=2, json_schema_extra=ui("IndexTTS 时长倍率"))
    default_emotion: str = Field(default="日常", json_schema_extra=ui("IndexTTS 默认语气"))
    emotions: list[str] = Field(default_factory=lambda: ["日常"], json_schema_extra=ui("IndexTTS 可选语气"))
    source: str = Field(default="", max_length=1000, json_schema_extra=ui("声音素材来源与使用说明"))


class RolesSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "角色"
    items: list[Role] = Field(default_factory=lambda: [Role(id="xiaoxiao", name="晓晓"), Role(id="xingnai", name="星奈（待导入声音）", backend="index", voice=""), Role(id="yuebai", name="月白（待导入声音）", backend="index", voice="")], json_schema_extra=ui("角色列表"))

    @model_validator(mode="after")
    def unique(self):
        if len({r.id for r in self.items}) != len(self.items):
            raise ValueError("角色 ID 不能重复")
        return self


class EmotionsSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "IndexTTS 语气"
    presets: list[Emotion] = Field(default_factory=lambda: [Emotion()], json_schema_extra=ui("语气预设（其他语气需试听后添加）"))

    @model_validator(mode="after")
    def unique(self):
        if len({e.name for e in self.presets}) != len(self.presets):
            raise ValueError("语气名称不能重复")
        return self


class TranslationSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "中日翻译"
    model_task: str = Field(default="utils", json_schema_extra=ui("翻译模型任务"))
    keep_chinese: bool = Field(default=True, json_schema_extra=ui("日语语音保留中文原文"))


class AdminSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "管理员"
    qqs: list[str] = Field(default_factory=list, json_schema_extra=ui("管理员 QQ 号", hint="管理群聊角色、语音模式与资源导入导出"))


class VoiceboxConfig(PluginConfigBase):
    plugin: PluginSettings = Field(default_factory=PluginSettings)
    edge: EdgeSettings = Field(default_factory=EdgeSettings)
    index: IndexSettings = Field(default_factory=IndexSettings)
    roles: RolesSettings = Field(default_factory=RolesSettings)
    emotions: EmotionsSettings = Field(default_factory=EmotionsSettings)
    translation: TranslationSettings = Field(default_factory=TranslationSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
