# 验证记录

日期：2026-10-26。环境：Apple Silicon macOS；本机 MaiBot 1.3.14，SDK 2.16.0。下面的“通过”只适用于明确注明的检查，不扩展解释为全部部署验收通过。

| 项目 | 状态 | 证据与限制 |
|---|---|---|
| SDK 配置与 manifest v2 | 通过 | 本机 MaiBot `PluginManifest` 校验通过；SDK 可生成 WebUI Schema |
| 插件核心自动测试 | 通过 | 55 项，最近运行 0.74 秒：回复、权限、翻译、状态、资源、缓存、超时、桥接排队及分块音频读取；模型和发送使用 mock |
| Edge 真实中文合成 | 通过 | edge-tts 7.3.1；统一短句约 1.70 秒，29,952 字节 MP3；macOS 音频检查为单声道 24kHz、4.992 秒 |
| Edge QQ 播放 | 待验收 | 尚未指定授权测试会话，不向现有聊天发送测试消息 |
| IndexTTS 2.5 官方接口 | 已对照 | 固定源码 v2.5.0；Python 接口与语言、情绪参数已核对 |
| IndexTTS 模型实机合成 | 待验收 | GitHub 固定版本元数据已取得，但稀疏代码检出多次中断；35MB 源码归档下载不完整且不支持断点续传；HuggingFace 连接超时。尚未完成权重与独立环境部署，不能假报后端完成 |
| IndexTTS MPS／CPU 耗时与内存 | 待验收 | 提供桥接健康指标与 benchmark 工具，未承诺实时速度 |
| 情绪与音色人工试听 | 待验收 | 只内置日常；开心／安慰候选不作为已验证推荐发布 |
| QQ 附件、历史原文、无重复 | 待验收 | 单元测试通过，但不等同真实客户端验收 |
| GitHub 源码 | 已上传 | 2026-10-27 上传到 [Yang456233/maibot-voicebox](https://github.com/Yang456233/maibot-voicebox) |
| GitHub Release | 以发布页为准 | [查看预发布与安装包](https://github.com/Yang456233/maibot-voicebox/releases)；不能据此推断待验收项目已通过 |
| 插件商店 | 未提交 | 完成相应发布与验收门槛后提交，最终以维护者审核为准 |

本地试听音频保存在开发目录 `artifacts/`，不进入仓库或插件包。未下载、打包或发布任何用户参考音频。

## 2026-10-27 CI 调度修正

[运行 40359681784](https://github.com/Yang456233/maibot-voicebox/actions/runs/40359681784) 的 Ubuntu Python 3.11／3.13 检查全部通过。两组 macOS 任务没有执行任何测试步骤：GitHub 注明 ARM runner 容量不足，多次分配失败后取消任务。这不是单元测试断言失败。

CI 将 macOS 改为官方标准 `macos-15-intel`，保留 Python 3.11／3.13、全部测试及打包检查，并关闭矩阵 fail-fast，确保一组失败不会取消其他组。云端 macOS 检查覆盖 Intel；Apple Silicon 的本地验证不能等同于云端 ARM 矩阵通过。
