# 角色包 v1

管理员将**已解压目录**放到插件数据目录的 `imports/<包名>/`。命令只接收包名，不接收系统路径、URL 或脚本。包名可含文字、数字、下划线、短横线，最多 64 字。

```text
imports/my-star/
  role.json
  voice.wav
  happy.wav        # 可选情绪参考
```

`role.json` 示例：

```json
{
  "version": 1,
  "role": {
    "id": "my_star",
    "name": "我的星奈",
    "backend": "index",
    "reference": "voice.wav",
    "source": "本人录制，仅授权我的机器人使用",
    "language": "zh",
    "default_emotion": "日常",
    "emotions": ["日常", "开心"],
    "duration_factor": 1.0
  },
  "emotions": [
    {"name": "日常"},
    {"name": "开心", "reference": "happy.wav", "strength": 0.5}
  ]
}
```

运行 `/声匣 导入 my-star`，再 `/声匣 试听 my_star`。上例声音均由用户提供，示例开心语气不是已验收推荐预设。

规则：

- ID 由小写字母开头，其余可含小写字母、数字、`_`、`-`，最长 48 字符。名称可中文。
- IndexTTS 角色必须提供参考音频和非空来源说明。引用路径不得为绝对路径、包含 `..`、使用反斜杠或符号链接。
- 音频仅 WAV/MP3，单个不超过 20MB；服务还会解码并校验时长。清单最大 128KB。
- 先验证整个清单，再写入角色登记。已有同 ID 导入角色会被更新；新音频按内容 SHA-256 存储，更换音频不会复用旧缓存。
- 语气必须在清单中定义；角色仅允许选择 `emotions` 列表里的预设。默认语气需存在。
- `/声匣 导出 my_star` 将资源和 JSON 写到 `exports/my_star/`。不导出 token、URL、管理员、聊天绑定或聊天记录。
- 包内的 Python、Shell 或其他文件不会被执行或复制。目录不能作为自动安装包使用。

Edge 角色包设置 `backend: "edge"`、`voice` 和 `japanese_voice` 即可，不需要参考音频。Edge 不支持克隆或 IndexTTS 情绪向量；不要将调节音调宣传为克隆某个角色。
