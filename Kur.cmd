@echo off
setlocal
chcp 65001 >nul
title Network Magic - Kurulum
cd /d "%~dp0"

echo.
echo ========================================
echo   Network Magic - Kurulum ve Baslatma
echo ========================================
echo.

if not exist "app.py" (
  echo [HATA] app.py bulunamadi. Kur.cmd dosyasini proje klasorune koyun.
  pause
  exit /b 1
)

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  call py -3.13 --version >nul 2>nul && set "PY_CMD=py -3.13"
  if not defined PY_CMD (call py -3.12 --version >nul 2>nul && set "PY_CMD=py -3.12")
  if not defined PY_CMD (call py -3.11 --version >nul 2>nul && set "PY_CMD=py -3.11")
  if not defined PY_CMD (call py -3.10 --version >nul 2>nul && set "PY_CMD=py -3.10")
)

if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo [BILGI] Python 3.10 veya yenisi bulunamadi. Winget ile Python 3.11 kuruluyor...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo [HATA] Winget bulunamadi. Python 3.10+ kurup bu dosyayi yeniden calistirin:
    echo        https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
  winget install --id Python.Python.3.11 -e --scope user --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo [HATA] Python kurulumu basarisiz oldu. Python 3.10+ kurup yeniden deneyin.
    pause
    exit /b 1
  )
  if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PY_CMD="
    set "PY_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
  ) else (
    set "PY_CMD=py -3.11"
  )
)

if not defined PY_EXE (
  for /f "delims=" %%P in ('%PY_CMD% -c "import sys; print(sys.executable)"') do set "PY_EXE=%%P"
)

if not defined PY_EXE (
  echo [HATA] Python calistirilamadi. Kurulumu kontrol edip yeniden deneyin.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [BILGI] Proje icin Python ortami hazirlaniyor...
  "%PY_EXE%" -m venv ".venv"
  if errorlevel 1 (
    echo [HATA] Python sanal ortami olusturulamadi.
    pause
    exit /b 1
  )
)

echo [BILGI] Gerekli paketler kuruluyor veya guncelleniyor...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [HATA] Paketler kurulamadi. Internet baglantinizi kontrol edip yeniden deneyin.
  pause
  exit /b 1
)

echo [BILGI] Uygulama baslatiliyor...
call run.bat
exit /b %errorlevel%
