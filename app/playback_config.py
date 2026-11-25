"""Configure the pinned Qt FFmpeg backend before importing Qt Multimedia."""
import os
import sys


def configure_playback_environment(environ=None, platform=None):
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    if platform == "win32":
        # Qt 6.10.3's D3D11 TextureBridge can dereference a null decoded texture
        # in ID3D11Texture2D::GetDesc. Use the supported CPU transfer/upload path
        # instead of cross-device GPU texture sharing; hardware decoding stays on.
        environ.setdefault("QT_DISABLE_HW_TEXTURES_CONVERSION", "1")
