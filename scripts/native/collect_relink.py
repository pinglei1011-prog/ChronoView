"""Record exact linked archives and supply a relinking kit with LGPL sources."""
import hashlib
import json
from pathlib import Path
import re
import shutil

root = Path.cwd()
out = root / 'native-output'
text = (out / 'metadata/native-link.map').read_text(errors='replace')
archives = sorted(set(re.findall(r'(/opt/ffbuild/[^\s()]+\.a)', text)))
assert archives, 'No dependency archives identified in linker map'
folder = out / 'relink/lib'
folder.mkdir(parents=True, exist_ok=True)
manifest = []
for name in archives:
    source = Path(name)
    assert source.is_file(), name
    dest = folder / source.name
    shutil.copyfile(source, dest)
    manifest.append(dict(name=source.name, sha256=hashlib.sha256(source.read_bytes()).hexdigest(), size=source.stat().st_size))
include = out / 'relink/include'
for name in ('shaderc', 'spirv_cross', 'freetype2', 'harfbuzz'):
    source = Path('/opt/ffbuild/include') / name
    if source.is_dir():
        shutil.copytree(source, include / name)
for source in Path('/opt/ffbuild/include').glob('*.h'):
    shutil.copyfile(source, include / source.name)
pc = out / 'relink/pkgconfig'
shutil.copytree('/opt/ffbuild/lib/pkgconfig', pc)
(out / 'metadata/linked-archives.json').write_text(json.dumps(manifest, indent=2))
notices = out / 'notices'
for component in (root / 'native-work').iterdir():
    if component.is_dir():
        for source in component.glob('*/*'):
            if source.is_file() and any(s in source.name.lower() for s in ('license', 'copying', 'copyright', 'authors')):
                target = notices / component.name / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
print('Recorded linked archives:', ', '.join(a['name'] for a in manifest))
