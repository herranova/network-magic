# -*- mode: python ; coding: utf-8 -*-
# PyInstaller tarifi: tek dosyalık NetworkMagic.exe üretir.
# Kullanım: build.cmd  (veya: python -m PyInstaller --noconfirm --clean NetworkMagic.spec)
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("netmagic") + collect_submodules("qrcode.image")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[("templates", "templates"), ("static", "static")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Kullanılmayan ağır modüller exe boyutunu büyütmesin
    excludes=["tkinter", "PIL", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NetworkMagic",
    icon="static/img/icon-512.png",
    console=True,          # Adres bilgisi ve Ctrl+C ile kapatma için konsol penceresi
    uac_admin=True,        # Engelleme / onarım araçları yönetici hakkı ister
    upx=False,             # UPX antivirüs yanlış alarmlarını artırır
    strip=False,
    debug=False,
    bootloader_ignore_signals=False,
    runtime_tmpdir=None,
    disable_windowed_traceback=False,
)
