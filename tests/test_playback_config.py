from app.playback_config import configure_playback_environment


def test_windows_uses_safe_texture_transfer_without_disabling_hardware_decoding():
    env = {"QT_FFMPEG_DECODING_HW_DEVICE_TYPES": "d3d11va"}
    configure_playback_environment(env, "win32")
    assert env["QT_DISABLE_HW_TEXTURES_CONVERSION"] == "1"
    assert env["QT_MEDIA_BACKEND"] == "ffmpeg"
    assert env["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] == "d3d11va"


def test_explicit_diagnostic_overrides_are_preserved():
    env = {"QT_DISABLE_HW_TEXTURES_CONVERSION": "0", "QT_MEDIA_BACKEND": "windows"}
    configure_playback_environment(env, "win32")
    assert env == {"QT_DISABLE_HW_TEXTURES_CONVERSION": "0", "QT_MEDIA_BACKEND": "windows"}


def test_other_platforms_keep_their_normal_texture_path():
    env = {}
    configure_playback_environment(env, "linux")
    assert env == {"QT_MEDIA_BACKEND": "ffmpeg"}
