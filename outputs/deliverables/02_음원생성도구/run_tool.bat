@echo off
chcp 65001 >nul
REM AAC 음원 생성 도구 실행 (Python 3.9 이상 필요)
cd /d %~dp0
python -m aac_voice_tool.cli gui project\project.json
pause
