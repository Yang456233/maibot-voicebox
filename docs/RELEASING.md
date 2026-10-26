# 发布与上架

目标仓库：`Yang456233/maibot-voicebox`，插件 ID 永久保持 `github.Yang456233.maibot-voicebox`。

## 0.1.0 预发布

1. 更新 `VALIDATION.md`，明确区分自动测试、实际后端合成、QQ 投递和人工试听。不能将 mock 测试当作模型或 QQ 验收。
2. 运行 `python scripts/validate_release.py`、`python -m pytest -q`、`python scripts/package.py`。本机宿主的 manifest 校验也需通过。
3. 将源码上传到公开仓库 main 分支，确认没有 config.toml、token、聊天记录、参考音频或权重。自动安装包使用白名单，只有源代码、文档、示例和测试。
4. 创建 `v0.1.0` Tag，发布同版本的 **Prerelease**。manifest 版本必须为 `0.1.0`。发布说明注明尚未完成的实机验收；附件可使用本地打包 ZIP。
5. 按官方最新规则评估是否可提交商店。当前发布门槛是完成安装、两种后端基本联调与指定 QQ 会话验收；未满足时保留预发布和提交文案，不制造上架已完成的印象。

只有 Tag 或 Draft Release 不满足商店要求。正式 `1.0.0` 必须补全安装、实际合成、QQ 播放和主观试听验收。已收录版本的 Tag 和 commit 不应改写，修复应发新版本。

## 商店提交文案

按 [官方贡献流程](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md) 的 Add Plugin 模板填写：

- 插件 ID：`github.Yang456233.maibot-voicebox`
- GitHub 仓库：`https://github.com/Yang456233/maibot-voicebox`
- 简介：Edge 与独立 IndexTTS 2.5 角色语音，支持会话声音绑定、受限情绪预设、中日翻译及失败文字回退。
- 版本：对应公开 Release，初始为 `0.1.0`。
- 兼容：MaiBot 1.3.14–1.3.99、SDK 2.16.0–2.16.99，目标 SnowLuma QQ；扩大范围前重新验证。

等待自动校验并处理反馈，最终是否上架由维护者审核决定。当前官方流程要求公开仓库、根目录 manifest v2、plugin.py、LICENSE、至少一个已发布 Release；规则核对日期为 2026-10-26，实际提交当天再次核对。

## 回归清单

- Edge 与 Index：正常、空音频、连接失败、总超时；模型只加载一次，队列过载不会并发推理。
- 角色包：路径越界、符号链接、缺音频、重复 ID 更新、音频指纹失效、导出无密钥。
- 翻译：原文模式零翻译调用；日语成功、失败、空结果、音色语言不匹配。
- 接入：自动／持续／下次语音、多个会话、同一回复重复回调、其他插件通知及已有语音。
- 发送：保留附件与原文历史；明确失败仅一次文字回退；未知结果不重发。
- 生命周期：重启恢复、热更新、卸载取消任务、版本不兼容时保留状态文件并报错。
- 实际试听：同一句分别日常、开心和安慰；记录清晰度、音色一致性、情绪可辨识度和等待时间。
