# Windows one-folder build. Copy the entire output folder, not only the EXE.
from pathlib import Path
import runpy
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
version = runpy.run_path(str(root / 'app' / '__init__.py'))['__version__']
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
    binaries=heif_binaries + [(str(root / 'vendor/libmpv/libmpv-2.dll'), 'vendor/libmpv')],
    datas=[(str(root / 'assets'), 'assets')] + heif_data +
          [(str(root / 'vendor/libmpv/manifest.json'), 'vendor/libmpv')],
    hiddenimports=heif_imports,
    hookspath=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtQml', 'PySide6.QtQuick', 'imageio_ffmpeg', 'pytest'],
    noarchive=False,
)
# Qt 6.10 uses the Windows 10/11 system ICU API (unversioned exports).
# Some development PATHs contain Conda/Poppler ICU with versioned exports.
# PyInstaller can incorrectly collect that DLL and shadow the Windows one.
# Keep ICU supplied by Windows; do not redistribute an unrelated PATH copy.
a.binaries = [entry for entry in a.binaries
              if not (Path(entry[0]).name.lower() in {'icuuc.dll', 'icuin.dll'}
                      or Path(entry[0]).name.lower().startswith('icudt'))]
# Generic Qt hooks also discover PDF/virtual-keyboard plugins. They are unused
# by this local media viewer and pull in unrelated Qt modules and licenses.
a.binaries = [entry for entry in a.binaries if not (
    Path(entry[0]).name.lower().startswith(('qt6qml', 'qt6quick', 'qt6virtualkeyboard', 'qt6pdf'))
    or 'virtualkeyboard' in entry[0].lower()
    or Path(entry[0]).name.lower() == 'qpdf.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ChronoView',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False, icon=str(root / 'assets/chronoview.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name=f'ChronoView-{version}')
