@echo off
chcp 65001 >nul
title Network Magic
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 if not exist ".venv\Scripts\python.exe" (
  echo [HATA] Python bulunamadi. https://www.python.org/downloads/ adresinden Python 3.10+ kurun.
  pause
  exit /b 1
)

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

"%PYTHON_EXE%" -c "import flask, psutil, qrcode" >nul 2>nul
if errorlevel 1 (
  echo Gerekli paketler kuruluyor...
  "%PYTHON_EXE%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [HATA] Paketler kurulamadi.
    pause
    exit /b 1
  )
)

net session >nul 2>nul
if errorlevel 1 (
  echo Yonetici haklari isteniyor ^(cihaz engelleme ve onarim araclari icin^)...
  powershell -NoProfile -Command "Start-Process -FilePath '%PYTHON_EXE%' -ArgumentList 'app.py' -WorkingDirectory '%CD%' -Verb RunAs"
  exit /b 0
)

"%PYTHON_EXE%" app.py
if errorlevel 1 pause
