@echo off
chcp 65001 >nul
REM Windows 실행 파일(AACVoiceTool.exe) 빌드 — Windows PC에서 실행
cd /d %~dp0
python -m pip install pyinstaller
python -m PyInstaller --onefile --name AACVoiceTool --paths ..\03_어휘세트패키지_규격서_및_도구 launcher.py
echo 생성: dist\AACVoiceTool.exe  (project 폴더와 같은 위치에 두고 실행)
pause
