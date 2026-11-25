"""Read-only library identity; drive letters are aliases, never disk identities."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LibraryIdentity:
    volume_guid: str
    volume_serial: str
    relative_root: str
    quality: str = "volume"

    @property
    def key(self):
        payload = json.dumps((self.volume_guid.casefold(), self.volume_serial.casefold(),
                              os.path.normcase(self.relative_root),
                              self.quality), separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalized_root(root: Path) -> str:
    return os.path.normcase(os.path.abspath(root))


def library_identity(root: Path) -> LibraryIdentity | None:
    """No writes to the media volume. Failure means 'unverified', not 'same disk'.

    A mounted volume can be identified even if its selected subdirectory was
    removed. Disconnected media has no live identity and may only use an explicit
    offline alias. A stat fallback is deliberately path-bound and does not infer
    that a disk moved to another drive letter.
    """
    root = Path(os.path.abspath(root))
    if os.name == "nt":
        try:
            # Resolve an explicitly selected junction root to its actual volume;
            # the scanner still uses the user-selected alias for display/paths.
            root = root.resolve()
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            volume_path = ctypes.create_unicode_buffer(32768)
            get_path = kernel.GetVolumePathNameW
            get_path.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
            get_path.restype = ctypes.c_int
            # GetVolumePathName supports a nonexistent final path. Some volume
            # providers require an existing ancestor, so walk only on failure.
            probe = root
            while not get_path(str(probe), volume_path, len(volume_path)):
                if probe.parent == probe:
                    break
                probe = probe.parent
            else:
                guid = ctypes.create_unicode_buffer(128)
                get_guid = kernel.GetVolumeNameForVolumeMountPointW
                get_guid.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
                get_guid.restype = ctypes.c_int
                get_info = kernel.GetVolumeInformationW
                get_info.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
                                     ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
                                     ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p, ctypes.c_uint32)
                get_info.restype = ctypes.c_int
                serial, max_component, flags = ctypes.c_uint32(), ctypes.c_uint32(), ctypes.c_uint32()
                if get_guid(volume_path.value, guid, len(guid)) and get_info(
                        volume_path.value, None, 0, ctypes.byref(serial), ctypes.byref(max_component),
                        ctypes.byref(flags), None, 0):
                    relative = os.path.relpath(str(root), volume_path.value).replace("\\", "/")
                    return LibraryIdentity(guid.value.rstrip("\\"), f"{serial.value:08x}", relative)
        except (OSError, ValueError, RuntimeError):
            pass
    try:
        info = root.stat()
        if not root.is_dir():
            return None
        if not info.st_dev or not info.st_ino:
            return None
        return LibraryIdentity(f"stat:{info.st_dev}", str(info.st_ino), normalized_root(root), "stat")
    except OSError:
        return None
