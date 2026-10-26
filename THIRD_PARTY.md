# 开源参考与素材边界

本项目自有实现采用 MIT，署名 Yang456233。没有复制下列插件的实现代码；接口、会话策略与测试均按 MaiBot SDK 2.16.0 重新实现。后续如复制 MIT 代码，需要同时保留原作者版权行和 MIT 全文；不能用本项目 MIT 标记覆盖上游代码或素材。

| 项目 | 参考内容 | 使用方式 |
|---|---|---|
| [OLDnana1/maibot-edge-tts](https://github.com/OLDnana1/maibot-edge-tts) | 中文配置、缓存、冷却、重试、发送结果检查 | 设计参考，不复制实现 |
| [xuqian13/tts_voice_plugin](https://github.com/xuqian13/tts_voice_plugin) | 统一 TTS 后端分离 | 自行实现 Provider 接口 |
| [YunChenqwq/EasyttsPlugin](https://github.com/YunChenqwq/EasyttsPlugin) | 角色与情绪选择体验 | 设计参考 |
| [A-Dawn/A_TTS_Plugin](https://github.com/A-Dawn/A_TTS_Plugin) | 会话语音模式 | SDK 2.16.0 重新实现 |
| [index-tts/index-tts](https://github.com/index-tts/index-tts/tree/v2.5.0) | IndexTTS 2.5 官方 Python 接口 | 独立环境运行，通过自有桥接服务调用 |
| [rany2/edge-tts](https://github.com/rany2/edge-tts) | Edge 在线合成客户端 | Python 依赖；受其上游许可及服务条款约束 |

研究 AGPL/GPL 项目不意味着可以把其代码重新标注为 MIT。本仓库不包含第三方插件实现、模型权重或声音样本。IndexTTS 的代码、模型及 bilibili Model Use License Agreement 等上游条款须单独阅读，以所用版本的 [官方许可证](https://github.com/index-tts/index-tts/blob/v2.5.0/LICENSE) 和模型卡为准。

“星奈”“月白”只是本项目原创模板名称。用户提供音频并记录来源与使用说明；角色包的音频许可由提供者单独声明，不随插件 MIT 自动授权。
