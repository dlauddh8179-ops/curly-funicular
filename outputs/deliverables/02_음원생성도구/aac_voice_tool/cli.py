"""명령줄 사용:
  python -m aac_voice_tool.cli synth   project.json [--id 3] [--missing]
  python -m aac_voice_tool.cli package project.json [--codec adpcm|pcm16]
  python -m aac_voice_tool.cli gui     project.json [--port 8765]
"""
import argparse
from .project import Project


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("synth"); s.add_argument("project"); s.add_argument("--id", type=int); s.add_argument("--missing", action="store_true")
    k = sp.add_parser("package"); k.add_argument("project"); k.add_argument("--codec", default="adpcm")
    g = sp.add_parser("gui"); g.add_argument("project"); g.add_argument("--port", type=int, default=8765); g.add_argument("--no-browser", action="store_true")
    a = p.parse_args()
    pr = Project(a.project)
    if a.cmd == "synth":
        if a.id: print(pr.synthesize(a.id))
        else:
            ok, fail = pr.synthesize_all(a.missing); print(f"완료 {ok}건, 실패 {len(fail)}건")
    elif a.cmd == "package":
        out, n = pr.build_package(a.codec); print(f"패키지 생성: {out} ({n:,} bytes)")
    else:
        from .gui import serve
        serve(pr, a.port, not a.no_browser)


if __name__ == "__main__":
    main()
