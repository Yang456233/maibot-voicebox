from typing import ClassVar, Literal
from maibot_sdk import Field, PluginConfigBase
from pydantic import model_validator


def ui(label, **extra):
    return {"label": label, **extra}


class PluginSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "插件与行为"
    enabled: bool = Field(default=True, json_schema_extra=ui('启用声匣', hint='关闭后停止语音转换；不删除角色与会话设置。'))
    config_version: str = Field(default="0.1.0", json_schema_extra=ui("配置版本", hidden=True))
    default_role: str = Field(default="xiaoxiao", json_schema_extra=ui('默认角色 ID', hint='填写角色列表中的 ID，例如 xiaoxiao；已有会话绑定请用 /声匣 切换 修改。'))
    max_text_length: int = Field(default=200, ge=10, le=500, json_schema_extra=ui('语音最大字数', hint='10～500，默认 200；超长保留文字，不截断。'))
    timeout: float = Field(default=45, ge=5, le=50, json_schema_extra=ui('含排队与翻译的总超时（秒）', hint='5～50，默认 45；超时回退文字，保持小于宿主 60 秒回复扩展预算。'))
    cooldown: float = Field(default=3, ge=0, le=60, json_schema_extra=ui('每会话语音间隔（秒）', hint='0～60，默认 3；试听和朗读也受限制，冷却中保留文字。'))
    cache_entries: int = Field(default=32, ge=0, le=128, json_schema_extra=ui('音频缓存条数', hint='0～128，默认 32；填 0 关闭缓存，重载或 /声匣 清缓存 可清除。'))
    cache_mb: int = Field(default=32, ge=1, le=128, json_schema_extra=ui('缓存容量（MB）', hint='1～128，默认 32；与缓存条数共同限制内存占用。'))


class EdgeSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "Edge 服务"
    proxy: str = Field(default="", json_schema_extra=ui('代理地址（可留空）', hint='留空直连；连接失败时填写可用代理，如 http://127.0.0.1:7890，端口以你的代理软件为准。'))
    retries: int = Field(default=1, ge=0, le=2, json_schema_extra=ui('合成重试次数', hint='0～2，默认 1：首次失败后再试一次，仍受总超时限制。'))


class IndexSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "IndexTTS 服务"
    url: str = Field(default="http://127.0.0.1:7861", json_schema_extra=ui('声匣桥接服务地址', hint='填写本项目桥接服务根地址，不加 /v1；仅使用 Edge 时无需启动。远程必须 HTTPS。'))
    token: str = Field(default="", json_schema_extra=ui('服务密钥', input_type="password", hint='本机未设置鉴权时留空；远程填写与服务端 VOICEBOX_TOKEN 相同的密钥。'))


class Emotion(PluginConfigBase):
    name: str = Field(default="日常", min_length=1, max_length=30, json_schema_extra=ui('语气名称', hint='命名预设，例如 日常；角色的默认语气和可选语气引用此名称。'))
    vector: list[float] = Field(default_factory=lambda: [0, 0, 0, 0, 0, 0, 0, 0], json_schema_extra=ui("情绪向量", hint="8 项：开心、生气、悲伤、害怕、厌恶、低落、惊讶、平静；仅 IndexTTS"))
    reference: str = Field(default="", json_schema_extra=ui('情绪参考音频（资源目录内相对路径，可空）', placeholder='xingnai/happy.wav（可留空）', hint='相对于插件数据目录 assets/；填写后优先使用参考音频，忽略情绪向量。'))
    strength: float = Field(default=0.6, ge=0, le=1, json_schema_extra=ui('情绪强度', hint='0～1，默认 0.6；传给 IndexTTS emo_alpha，具体作用以模型实现和试听为准。'))

    @model_validator(mode="after")
    def validate_vector(self):
        if len(self.vector) != 8 or any(not 0 <= v <= 1 for v in self.vector):
            raise ValueError("情绪向量必须为 8 个 0～1 数值")
        return self


class Role(PluginConfigBase):
    id: str = Field(default="role", pattern=r"^[a-z][a-z0-9_-]{0,47}$", json_schema_extra=ui('角色 ID', hint='稳定且唯一；小写字母开头，可含数字、下划线和短横线，最多 48 字符。'))
    name: str = Field(default="角色", min_length=1, max_length=50, json_schema_extra=ui('角色名称', hint='显示名称，可中文；不会改变麦麦的人格。'))
    backend: Literal["edge", "index"] = Field(default="edge", json_schema_extra=ui('语音引擎', hint='edge 使用在线预设音色；index 使用独立 IndexTTS 服务与参考音频。'))
    language: Literal["zh", "ja", "en"] = Field(default="zh", json_schema_extra=ui('原文默认语言', hint='zh 中文、ja 日语、en 英语；原文模式不翻译，Edge 音色须匹配此语言。'))
    voice: str = Field(default="zh-CN-XiaoxiaoNeural", json_schema_extra=ui('Edge 音色 ID', placeholder='zh-CN-XiaoxiaoNeural', hint='例如 zh-CN-XiaoxiaoNeural；填写服务返回的 ShortName，不是角色昵称或音频路径。'))
    japanese_voice: str = Field(default="ja-JP-NanamiNeural", json_schema_extra=ui('Edge 日语音色 ID', placeholder='ja-JP-NanamiNeural', hint='例如 ja-JP-NanamiNeural；切到“日语”模式时使用，原文模式使用上面的音色。'))
    reference: str = Field(default="", json_schema_extra=ui('IndexTTS 角色音频（资源目录内相对路径）', placeholder='xingnai/voice.wav（相对 assets/）', hint='例如 xingnai/voice.wav，先放入插件数据目录 assets/；不要填绝对路径或 URL。'))
    rate: int = Field(default=0, ge=-50, le=100, json_schema_extra=ui('Edge 语速（%）', hint='-50～100，默认 0；正数加快，负数放慢，只填数字。'))
    pitch: int = Field(default=0, ge=-50, le=50, json_schema_extra=ui('Edge 音调（Hz）', hint='-50～50，默认 0；正数升高，负数降低，只填数字。'))
    volume: int = Field(default=0, ge=-100, le=100, json_schema_extra=ui('Edge 音量（%）', hint='-100～100，默认 0；相对音量调整，不是绝对音量百分比。'))
    duration_factor: float = Field(default=1, ge=0.5, le=2, json_schema_extra=ui('IndexTTS 时长倍率', hint='0.5～2，默认 1；直接传给模型 duration_factor，先保留 1 再试听调整。'))
    default_emotion: str = Field(default="日常", json_schema_extra=ui('IndexTTS 默认语气', hint='应在可选语气列表及语气预设中存在；AI 未选或选错时回退此项。'))
    emotions: list[str] = Field(default_factory=lambda: ["日常"], json_schema_extra=ui('IndexTTS 可选语气', hint='填写已定义的预设名称，如 日常；AI 只能从此列表中选。Edge 忽略此项。'))
    source: str = Field(default="", max_length=1000, json_schema_extra=ui('声音素材来源与使用说明', placeholder='本人录制；仅用于自己的机器人', hint='记录录制者或素材来源、授权范围；IndexTTS 角色包导入要求非空。'))


class RolesSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "角色"
    items: list[Role] = Field(default_factory=lambda: [Role(id="xiaoxiao", name="晓晓"), Role(id="xingnai", name="星奈（待导入声音）", backend="index", voice=""), Role(id="yuebai", name="月白（待导入声音）", backend="index", voice="")], json_schema_extra=ui('角色列表', hint='声源在这里配置：Edge 填音色 ID；IndexTTS 填 assets/ 内参考音频路径。添加角色后保存，再 /声匣 试听 <ID>。'))

    @model_validator(mode="after")
    def unique(self):
        if len({r.id for r in self.items}) != len(self.items):
            raise ValueError("角色 ID 不能重复")
        return self


class EmotionsSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "IndexTTS 语气"
    presets: list[Emotion] = Field(default_factory=lambda: [Emotion()], json_schema_extra=ui('语气预设（其他语气需试听后添加）', hint='只作用于 IndexTTS；角色通过名称引用。全零向量且无参考音频表示默认表达。'))

    @model_validator(mode="after")
    def unique(self):
        if len({e.name for e in self.presets}) != len(self.presets):
            raise ValueError("语气名称不能重复")
        return self


class TranslationSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "中日翻译"
    model_task: str = Field(default="utils", json_schema_extra=ui('翻译模型任务', hint='默认 utils；使用麦麦中已配置的模型任务名称，只在日语模式调用。'))
    keep_chinese: bool = Field(default=True, json_schema_extra=ui('日语语音保留中文原文', hint='默认开启；日语合成时保留原文文字，翻译失败仍回退原文。'))


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
