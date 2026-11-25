"""Install, re-install, exercise and uninstall in an isolated current-user folder."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import winreg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import __version__

installer = ROOT / "dist" / f"ChronoView-{__version__}-setup-win64.exe"
work = ROOT / "work" / f"installer-{__version__}"
app = work / "安装测试 with spaces"
work.mkdir(parents=True, exist_ok=True)
assert not (app / "unins000.exe").exists(), "Finish the previous isolated uninstall before retrying"
key_name = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{8A2E56B4-A023-4A20-A995-55C7707CF23D}_is1"


def installed():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, "InstallLocation")[0]
    except FileNotFoundError:
        return None


assert installed() is None, "A user's installed copy exists; do not replace it with this test"
info = subprocess.STARTUPINFO()
info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
info.wShowWindow = 0


def run(command, timeout=180):
    result = subprocess.run([str(s) for s in command], cwd=work, startupinfo=info, timeout=timeout)
    assert result.returncode == 0, f"Command failed ({result.returncode}): {command[0]}"


args = [installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
        f"/DIR={app}", "/TASKS="]
run(args + [f"/LOG={work / 'install.log'}"])
assert Path(installed()).resolve() == app.resolve()
assert (app / "ChronoView.exe").is_file()
assert (app / "_internal/vendor/libmpv/libmpv-2.dll").is_file()
shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/ChronoView/ChronoView.lnk"
assert shortcut.is_file(), "Start Menu shortcut was not created"
runtime = ROOT / "dist" / f"ChronoView-{__version__}" / "ChronoView.exe"
assert hashlib.sha256(runtime.read_bytes()).digest() == hashlib.sha256((app / "ChronoView.exe").read_bytes()).digest()
assert (app / "VALIDATION.md").read_bytes() == (runtime.parent / "VALIDATION.md").read_bytes()
marker = app / "user-unlisted-file.txt"
marker.write_text("Preserve this user file during upgrade and uninstall", encoding="utf-8")
external = work / "user-settings-and-media-marker.txt"
external.write_text("External user data is not owned by the installer", encoding="utf-8")
expected = external.read_bytes()
run(args + [f"/LOG={work / 'reinstall.log'}"])
assert marker.is_file() and external.read_bytes() == expected
run([sys.executable, ROOT / "scripts/verify_portable.py", "--executable", app / "ChronoView.exe"])
media = json.loads((ROOT / "work" / f"packaged-{__version__}-media.json").read_text(encoding="utf-8"))
assert media["success"] and media["video_backend"] == "libmpv"
run([app / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={work / 'uninstall.log'}"])
assert not (app / "ChronoView.exe").exists()
assert not (app / "_internal/vendor/libmpv/libmpv-2.dll").exists()
assert marker.is_file() and external.read_bytes() == expected
assert installed() is None
assert not shortcut.exists()
report = dict(success=True, version=__version__, current_user_install=True,
              installer_sha256=hashlib.sha256(installer.read_bytes()).hexdigest(),
              start_menu_shortcut_created_and_removed=True,
              reinstall_preserves_unlisted_file=True, installed_playback=media["success"],
              uninstall_removes_runtime_and_registration=True,
              uninstall_preserves_unlisted_and_external_files=True)
(work / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report), flush=True)
