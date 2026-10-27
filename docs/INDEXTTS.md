# IndexTTS 2.5 独立部署

插件连接本仓库的桥接协议，不兼容任意第三方 WebUI 的 `/tts` 接口。MaiBot 与模型服务使用不同 Python 环境。桥接代码按官方 **v2.5.0**（`39207d91c30899cad1e7c1b9eb678c241f678e55`）接口编写。模型权重为 **IndexTeam/IndexTTS-2.5**，更换权重后设置新的 `INDEX_MODEL_REVISION` 并清空插件缓存。

## 安装模型环境

以下操作由用户在单独目录明确执行，插件不会自动运行安装命令。先阅读 [官方安装说明](https://github.com/index-tts/index-tts/tree/v2.5.0) 和对应模型许可。

```sh
git clone --branch v2.5.0 --depth 1 https://github.com/index-tts/index-tts.git
cd index-tts
uv sync
uv pip install -r /绝对路径/maibot-voicebox/bridge/requirements.txt
uv run --no-sync hf download IndexTeam/IndexTTS-2.5 --local-dir checkpoints
```

若环境没有 `hf`，按官方说明使用独立 `uv tool install huggingface-hub` 后运行 `hf download`。不要对麦麦的环境执行这一步。需要可复现的模型权重时，在下载命令附加 `--revision <模型仓库提交 SHA>`，并将相同 SHA 记入 `INDEX_MODEL_REVISION`。官方模型首次推理可能还需要下载辅助模型。

桥接不依赖 WebUI，不需要为了它安装 DeepSpeed 或 Gradio。上传标准 PCM WAV 不依赖 FFmpeg；MP3 或其他编码 WAV 需要在**模型服务端**安装 FFmpeg。建议参考音频为单人、无背景音乐、0.5～30 秒的清晰声音，单文件最大 20MB。

## 本地启动

从声匣仓库执行（替换成自己的绝对路径）：

```sh
python scripts/start_bridge.py \
  --index-root /绝对路径/index-tts \
  --model-dir /绝对路径/index-tts/checkpoints \
  --data-dir /绝对路径/voicebox-service-data \
  --device auto
```

启动工具选择 IndexTTS 自己的 `.venv`，不会选择麦麦的 Python。先等待健康检查 `ready=true`，再在插件配置填写 `http://127.0.0.1:7861`。自动设备选择由官方接口执行；Apple Silicon 可尝试 `--device mps`，不支持时用 `--device cpu` 重新启动。没有实际测量前，不承诺 Mac CPU/MPS 的实时速度。

```sh
curl http://127.0.0.1:7861/v1/health
```

浏览器直接打开 `http://127.0.0.1:7861/` 可查看服务名称和模型状态；这是供插件调用的桥接服务，不是角色管理页面。详细状态在 `/v1/health`，角色配置仍在麦麦 WebUI。

`ready=false` 表示模型加载中或失败。服务不会在模型未加载时假报健康。健康数据含加载耗时、进程峰值 RSS（支持的平台）和请求设备；峰值 RSS 不是独占显存测量。

## 远程部署

在 GPU 服务器安装同一桥接。通过环境变量 `VOICEBOX_TOKEN` 设置随机密钥。默认仅监听 `127.0.0.1`，推荐继续保持本机监听，通过 HTTPS 反向代理暴露；反向代理转发 `Authorization`，限制请求体约 21MB，并限制访问来源。插件端填写 HTTPS URL 和相同密钥。禁止将 token 写在 URL 中。

必须直接对外监听时，启动参数使用 `--host 0.0.0.0`，且必须先配置 token；外部客户端仍通过 HTTPS 代理访问。服务不自动申请证书。插件会拒绝“非本机 HTTP”或“远程无 token”的配置。

示例反向代理规则（替换域名与 TLS 部署）：

```caddy
voice.example.org {
    request_body {
        max_size 21MB
    }
    reverse_proxy 127.0.0.1:7861
}
```

## 协议 v1

| 接口 | 请求／返回 |
|---|---|
| `GET /v1/health` | API 版本、引擎、模型版本、ready、排队数量与加载状态 |
| `GET /v1/capabilities` | 语言、情绪顺序、参考音频限制 |
| `POST /v1/references` | multipart `file`，返回内容指纹 `resource_id` |
| `POST /v1/synthesize` | JSON 参数，返回 `audio/wav` |

```json
{
  "text": "今天也辛苦了。",
  "language": "zh",
  "reference_id": "上传接口返回的64位十六进制资源ID",
  "emotion_vector": [0.5, 0, 0, 0, 0, 0, 0, 0],
  "emotion_strength": 0.6,
  "duration_factor": 1.0
}
```

`emotion_reference_id` 和 `emotion_vector` 互斥；都不填表示默认表达。向量顺序：开心、生气、悲伤、害怕、厌恶、低落、惊讶、平静。首版不启用模型的自由文本情绪推断。模型内 `emo_alpha` 对向量和情绪参考音频的实际影响以官方实现为准。

模型只加载一次。一个 worker 串行推理，最多两项等待；队列满返回 429，模型不可用返回 503，超时返回 504。HTTP 超时不会强行停止已进入底层模型的计算，worker 会等计算结束，再处理下一项，确保不会偷偷并发。过期排队任务直接丢弃。退出服务会等待当前推理结束。

引用文件均由服务保存，Mac 的绝对路径不会发送到服务器。参考素材最多保存 256 份；达到上限时停止上传，管理员停服后清理 `references/` 中无用资源。插件下次合成会重新上传需要的素材。

## 验收与性能记录

```sh
.venv/bin/python scripts/benchmark_bridge.py --reference /绝对路径/自己的参考.wav
```

该工具使用插件开发环境的 httpx，向桥接生成中日语、日常／开心实验／安慰实验音频，并保存耗时与健康指标。不会向 QQ 发送消息，也不会改动角色配置。请人工记录清晰度、音色一致性、情绪可辨识度；“安慰”向量只是实验候选，未经试听不作为推荐预设。

分别在 MPS 和 CPU 服务中运行，记录首次加载、首条与后续耗时和峰值内存。若超过插件 45 秒总预算，应换用更快的远程模型服务；不要把宿主 Hook 超时当作无限等待方案。
