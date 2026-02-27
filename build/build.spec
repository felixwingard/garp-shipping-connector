# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec för GARP Shipping Connector
# Bygg med: pyinstaller build/build.spec (build.bat gör cd till projektrot)
import os
# Hitta projektrot (mapp som innehåller src/ och build/)
_cwd = os.getcwd()
_proj = _cwd if os.path.isdir(os.path.join(_cwd, 'src')) else os.path.normpath(os.path.join(_cwd, '..'))
_spec_dir = os.path.join(_proj, 'build')

a = Analysis(
    [os.path.join(_spec_dir, 'entry.py')],  # Bootstrap — absolut import till src.main
    pathex=[_proj],  # Projektrot så att 'src' hittas
    binaries=[],
    datas=[
        ('../config/config.example.yaml', 'config'),
    ],
    hiddenimports=[
        'src',
        'src.main',
        'src.service',
        'src.tray',
        'src.tray.app',
        'src.utils.config',
        'win32timezone',
        'win32serviceutil',
        'win32service',
        'win32event',
        'servicemanager',
        'win32print',
        'win32api',
        'yaml',
        'watchdog',
        'watchdog.observers',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'openpyxl.worksheet',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GarpShippingConnector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,      # Windowed — ingen svart konsolfönster
    icon=None,           # TODO: Lägg till .ico-fil
)
