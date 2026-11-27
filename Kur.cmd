@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Network Magic - Kurulum
cd /d "%~dp0"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "VPY=%~dp0.venv\Scripts\python.exe"

echo.
echo ========================================
echo   Network Magic - Kurulum ve Baslatma
echo ========================================
echo.

if not exist "app.py" (
  echo [HATA] app.py bulunamadi. Kur.cmd dosyasini proje klasorune koyun.
  goto :fail
)

rem ---------------------------------------------------------------
rem 1) Python 3.10+ bul, yoksa winget ile kur
rem ---------------------------------------------------------------
call :find_python
if defined PY_EXE goto :have_python

echo [BILGI] Python 3.10 veya yenisi bulunamadi. Winget ile Python 3.11 kuruluyor...
where winget >nul 2>nul
if errorlevel 1 (
  echo [HATA] Winget bulunamadi. Python 3.11 kurup bu dosyayi yeniden calistirin:
  echo        https://www.python.org/downloads/windows/
  echo        Kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
  goto :fail
)
winget install --id Python.Python.3.11 -e --scope user --accept-package-agreements --accept-source-agreements
call :find_python
if not defined PY_EXE (
  echo [HATA] Python kuruldu ama bulunamadi. Bilgisayari yeniden baslatip Kur.cmd'yi tekrar calistirin.
  goto :fail
)

:have_python
echo [OK] Python: %PY_EXE%

rem ---------------------------------------------------------------
rem 2) Proje icin sanal ortam (.venv) - bozuksa yeniden olustur
rem ---------------------------------------------------------------
if exist "%VPY%" (
  "%VPY%" -c "import sys, pip" >nul 2>nul
  if errorlevel 1 (
    echo [BILGI] Bozuk Python ortami bulundu, yeniden olusturuluyor...
    rmdir /s /q ".venv"
  )
)
if not exist "%VPY%" (
  echo [BILGI] Proje icin Python ortami hazirlaniyor...
  "%PY_EXE%" -m venv ".venv"
  if errorlevel 1 (
    echo [HATA] Python sanal ortami olusturulamadi.
    goto :fail
  )
)

rem ---------------------------------------------------------------
rem 3) Paketleri kur - ag hatalarina karsi 3 deneme
rem ---------------------------------------------------------------
"%VPY%" -c "import flask, psutil, qrcode" >nul 2>nul
if not errorlevel 1 goto :pkgs_ok

echo [BILGI] pip guncelleniyor...
"%VPY%" -m pip install --upgrade --prefer-binary --retries 5 --timeout 60 pip >nul 2>nul

set /a TRY=0
:pip_retry
set /a TRY+=1
echo.
echo [BILGI] Gerekli paketler indiriliyor - deneme %TRY%/3
if %TRY% EQU 1 (
  "%VPY%" -m pip install --prefer-binary --retries 5 --timeout 60 -r requirements.txt
) else (
  "%VPY%" -m pip install --prefer-binary --retries 10 --timeout 120 --no-cache-dir -r requirements.txt
)
"%VPY%" -c "import flask, psutil, qrcode" >nul 2>nul
if not errorlevel 1 goto :pkgs_ok
if %TRY% LSS 3 (
  echo [UYARI] Bazi paketler indirilemedi. 5 saniye sonra tekrar denenecek...
  timeout /t 5 /nobreak >nul
  goto :pip_retry
)

echo.
echo [HATA] Paketler 3 denemede de kurulamadi. Olasi nedenler:
echo        - Internet baglantisi kesik ya da cok yavas
echo        - VPN, proxy veya kurum guvenlik duvari pypi.org adresini engelliyor
echo        - Antivirus indirilen dosyalari engelliyor
echo        Cozum: Python gerektirmeyen NetworkMagic.exe surumunu kullanin:
echo        https://github.com/herranova/network-magic/releases/latest
goto :fail

:pkgs_ok
echo [OK] Paketler hazir.
echo [BILGI] Uygulama baslatiliyor...
call "%~dp0run.bat"
exit /b %errorlevel%

:fail
echo.
pause
exit /b 1

rem ---------------------------------------------------------------
rem Yardimci: PY_EXE degiskenine 3.10+ bir python.exe yolu yazar
rem ---------------------------------------------------------------
:find_python
set "PY_EXE="
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.12 3.11 3.13 3.10 3.14) do if not defined PY_EXE call :probe py -%%V
)
for %%D in (Python312 Python311 Python313 Python310 Python314) do (
  if not defined PY_EXE if exist "%LocalAppData%\Programs\Python\%%D\python.exe" set "PY_EXE=%LocalAppData%\Programs\Python\%%D\python.exe"
)
if not defined PY_EXE call :probe python
exit /b 0

:probe
for /f "delims=" %%P in ('%* -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2^>nul') do set "PY_EXE=%%P"
if defined PY_EXE if not exist "%PY_EXE%" set "PY_EXE="
exit /b 0
