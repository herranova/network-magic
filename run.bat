@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Network Magic
cd /d "%~dp0"

set "VPY=%~dp0.venv\Scripts\python.exe"

rem Kurulum eksik ya da yarim kaldiysa once Kur.cmd calissin.
if not exist "%VPY%" goto :need_setup
"%VPY%" -c "import flask, psutil, qrcode" >nul 2>nul
if errorlevel 1 goto :need_setup

rem Yonetici degilsek bu dosyayi UAC ile yeniden ac; reddedilirse sinirli modda devam et.
net session >nul 2>nul
if not errorlevel 1 goto :run
echo Yonetici haklari isteniyor - cihaz engelleme ve onarim araclari icin...
powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs -ErrorAction Stop } catch { exit 1 }"
if not errorlevel 1 exit /b 0
echo [UYARI] Yonetici izni verilmedi. Uygulama sinirli modda baslatiliyor...

:run
"%VPY%" app.py
if errorlevel 1 (
  echo.
  echo [HATA] Network Magic beklenmedik sekilde kapandi. Yukaridaki mesaji gelistiriciye iletin.
  pause
)
exit /b

:need_setup
echo [BILGI] Kurulum eksik. Kur.cmd calistiriliyor...
call "%~dp0Kur.cmd"
exit /b
