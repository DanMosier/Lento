# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

datas = [(f'PDF_to_MusicXML/{name}.py', 'PDF_to_MusicXML') for name in ('homr_bridge', 'system_reader', 'instruments', 'system_merge')]
binaries = []
hiddenimports = ['PDF_to_MusicXML', 'PDF_to_MusicXML.gui', 'PDF_to_MusicXML.cli', 'PDF_to_MusicXML.models', 'PDF_to_MusicXML.omr_engines', 'PDF_to_MusicXML.staff_detection', 'PDF_to_MusicXML.pdf_splitter', 'PDF_to_MusicXML.musicxml_parser', 'PDF_to_MusicXML.vst_catalog', 'PDF_to_MusicXML.audio_player', 'PDF_to_MusicXML.homr_runner']
datas += collect_data_files('certifi')
tmp_ret = collect_all('pypdfium2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pypdfium2_raw')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PdfToMusicXML',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
