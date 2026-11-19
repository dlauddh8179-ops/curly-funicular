"""실행 파일 진입점: 실행 파일과 같은 폴더의 project/project.json 을 열어 GUI 실행."""
import os, sys
from aac_voice_tool.project import Project
from aac_voice_tool.gui import serve

base = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
serve(Project(os.path.join(base, "project", "project.json")))
