# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('editor/map_index.json', 'editor')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'tkinter', 'pyboy', 'pytest'],
    noarchive=False,
    optimize=0,
)
# Qt loads the Windows ICU API. A Git or Conda installation on PATH may
# supply an incompatible icuuc.dll with version-suffixed exports.
a.binaries = [
    entry for entry in a.binaries
    if not Path(entry[0]).name.lower().startswith(("icuuc", "icudt"))
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PokemonRedSaveEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PokemonRedSaveEditor',
)
