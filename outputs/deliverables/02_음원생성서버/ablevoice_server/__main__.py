"""실행:
  python -m ablevoice_server serve  --data ./data --config server_config.json [--host 0.0.0.0 --port 8080]
  python -m ablevoice_server create-device --data ./data --id 1001 --name "홍길동 님"
  python -m ablevoice_server warm-cache --data ./data --config server_config.json   (문장 목록 160개 미리 합성)
"""
import argparse, json, sys
from .service import Service
from .api import serve


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("serve"); s.add_argument("--data", default="data"); s.add_argument("--config", default="server_config.json")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8080)
    c = sp.add_parser("create-device"); c.add_argument("--data", default="data"); c.add_argument("--id", required=True); c.add_argument("--name", default="")
    w = sp.add_parser("warm-cache"); w.add_argument("--data", default="data"); w.add_argument("--config", default="server_config.json")
    a = p.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8")) if getattr(a, "config", None) else {}
    if a.cmd == "serve":
        serve(a.data, cfg, a.host, a.port)
    elif a.cmd == "create-device":
        t = Service(a.data).create_device(a.id, a.name)
        print("기기 등록 완료. 아래 토큰은 다시 볼 수 없으니 보관하세요.")
        for k, v in t.items(): print(f"  {k:6s}: {v}")
    else:
        svc = Service(a.data, cfg); voice = {"voice": "", "rate": 0.85, "pitch": 1.0, "volume": 1.0}
        for i, (vid, text) in enumerate(sorted(svc.by_id.items()), 1):
            svc.tts(text, voice); print(f"\r  {i}/{len(svc.by_id)} {text}        ", end="")
        print()


if __name__ == "__main__":
    main()
