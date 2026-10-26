"""Run only inside the user's separate, already installed IndexTTS environment."""
import argparse
import os
from pathlib import Path

parser = argparse.ArgumentParser(description="启动独立 IndexTTS 桥接；不自动安装模型")
parser.add_argument("--index-root", type=Path, required=True)
parser.add_argument("--model-dir", type=Path, required=True)
parser.add_argument("--data-dir", type=Path, default=Path("voicebox-service-data"))
parser.add_argument("--device", choices=["auto", "mps", "cpu", "cuda"], default="auto")
parser.add_argument("--port", type=int, default=7861)
parser.add_argument("--host", default="127.0.0.1")
args = parser.parse_args()
root = args.index_root.resolve()
python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.is_file() or not (root / "indextts/infer_v2_5.py").is_file():
    parser.error("请先按部署指南在独立目录安装官方 IndexTTS v2.5.0")
if not (args.model_dir / "config.yaml").is_file():
    parser.error("模型目录缺少 config.yaml，请先下载 IndexTTS-2.5 权重")
env = dict(os.environ)
env.update(PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parents[1]), str(root)]),
    INDEX_MODEL_DIR=str(args.model_dir.resolve()), VOICEBOX_DATA=str(args.data_dir.resolve()),
    INDEX_DEVICE=args.device, VOICEBOX_HOST=args.host, VOICEBOX_PORT=str(args.port))
os.chdir(root)
os.execve(str(python), [str(python), "-m", "bridge.server"], env)
