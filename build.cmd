@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Network Magic - Build
cd /d "%~dp0"
set "VPY=%~dp0.venv\Scripts\python.exe"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

if not exist "%VPY%" (
  echo [HATA] .venv bulunamadi. Once Kur.cmd dosyasini calistirin.
  goto :fail
)

echo [1/3] Build araclari kuruluyor...
"%VPY%" -m pip install --prefer-binary --retries 5 --timeout 60 -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :fail

echo [2/3] Testler calistiriliyor...
"%VPY%" -m unittest discover -s tests
if errorlevel 1 goto :fail

echo [3/3] NetworkMagic.exe olusturuluyor...
"%VPY%" -m PyInstaller --noconfirm --clean NetworkMagic.spec
if errorlevel 1 goto :fail

echo.
echo [OK] Hazir: %~dp0dist\NetworkMagic.exe
exit /b 0

:fail
echo.
echo [HATA] Build basarisiz.
pause
exit /b 1
