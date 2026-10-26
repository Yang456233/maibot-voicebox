"""Explicit local/service tests, never sends chat messages."""
import argparse
import json
import os
from pathlib import Path
import time
import httpx

parser = argparse.ArgumentParser(description="测试桥接中日语及语气，生成音频与测量记录")
parser.add_argument("--reference", type=Path, required=True)
parser.add_argument("--url", default="http://127.0.0.1:7861")
parser.add_argument("--output", type=Path, default=Path("artifacts/index-benchmark"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
headers = {"Authorization": "Bearer " + os.environ["VOICEBOX_TOKEN"]} if os.getenv("VOICEBOX_TOKEN") else {}
report = {"subjective_listening": "未验收；不能把合成成功等同于音质通过", "results": []}
with httpx.Client(base_url=args.url, headers=headers, timeout=180) as client:
    response = client.get("/v1/health")
    response.raise_for_status()
    report["health_before"] = response.json()
    if not response.json()["ready"]:
        raise SystemExit("模型未就绪")
    with args.reference.open("rb") as f:
        response = client.post("/v1/references", files={"file": (args.reference.name, f)})
    response.raise_for_status()
    resource = response.json()["resource_id"]
    for language, text in [("zh", "今天也辛苦了。很高兴见到你，我们慢慢聊吧。"),
                            ("ja", "今日もお疲れさま。会えてうれしいです。ゆっくり話しましょう。")]:
        for name, vector in [("日常", None), ("开心_实验", [0.5, 0, 0, 0, 0, 0, 0, 0]),
                              ("安慰_实验", [0, 0, 0, 0, 0, 0, 0, 0.5])]:
            started = time.monotonic()
            body = {"text": text, "language": language, "reference_id": resource}
            if vector:
                body["emotion_vector"] = vector
            response = client.post("/v1/synthesize", json=body)
            row = {"language": language, "preset": name, "seconds": round(time.monotonic()-started, 3), "status": response.status_code}
            if response.status_code == 200:
                target = args.output / f"{language}-{name}.wav"
                target.write_bytes(response.content)
                row["file"] = target.name
            report["results"].append(row)
    report["health_after"] = client.get("/v1/health").json()
(args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
