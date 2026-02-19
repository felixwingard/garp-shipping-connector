# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec för GARP Shipping Connector
# Bygg med: pyinstaller build/build.spec

a = Analysis(
    ['../src/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../config/config.example.yaml', 'config'),
    ],
    hiddenimports=[
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
