# Windows one-folder build. Copy the entire output folder, not only the EXE.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
heif_data, heif_binaries, heif_imports = [], [], []
try:
    import pillow_heif
except ImportError:
    pass
else:
    heif_data, heif_binaries, heif_imports = collect_all('pillow_heif')

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=heif_binaries,
    datas=[(str(root / 'assets'), 'assets')] + heif_data,
    hiddenimports=heif_imports,
    hookspath=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtMultimedia',
              'PySide6.QtMultimediaWidgets', 'pytest'],
    noarchive=False,
)
# Qt 6.10 uses the Windows 10/11 system ICU API (unversioned exports).
# Some development PATHs contain Conda/Poppler ICU with versioned exports.
# PyInstaller can incorrectly collect that DLL and shadow the Windows one.
# Keep ICU supplied by Windows; do not redistribute an unrelated PATH copy.
a.binaries = [entry for entry in a.binaries
              if not (Path(entry[0]).name.lower() in {'icuuc.dll', 'icuin.dll'}
                      or Path(entry[0]).name.lower().startswith('icudt'))]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ChronoView',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ChronoView')
