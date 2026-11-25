"""Fetch only hash-locked native sources and unpack without path traversal."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request

root = Path.cwd()
lock = json.loads((root / 'scripts/native/sources.lock.json').read_text())
sources = root / 'native-output/sources'
sources.mkdir(parents=True, exist_ok=True)
work = root / 'native-work'
work.mkdir(exist_ok=True)
for entry in lock['sources']:
    archive = sources / entry['archive']
    if not archive.exists():
        with urllib.request.urlopen(entry['url'], timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != entry['sha256']:
        raise RuntimeError('Source checksum mismatch: ' + entry['name'])
    folder = work / entry['name']
    folder.mkdir(exist_ok=True)
    with tarfile.open(archive) as source:
        source.extractall(folder, filter='data')
    top = [p for p in folder.iterdir() if p.is_dir()]
    assert len(top) == 1
    print('Verified', entry['name'], entry['revision'], flush=True)
shutil.copyfile(root / 'scripts/native/sources.lock.json', root / 'native-output/metadata/sources.lock.json')
