import ctypes as C
from ctypes import wintypes as W
import hashlib
from pathlib import Path
import sys

from PIL import Image, UnidentifiedImageError
import pytest

from app.core.scanner import scan_library
from app.services.images import image_error_message, read_image


@pytest.mark.parametrize('contents', [b'', b'corrupt photo bytes'])
def test_empty_and_corrupt_images_are_friendly_and_read_only(tmp_path, contents):
    path = tmp_path / 'IMG20261125120000.jpg'
    path.write_bytes(contents)
    before = hashlib.sha256(path.read_bytes()).digest()
    with pytest.raises(UnidentifiedImageError) as error:
        read_image(path)
    assert '无法识别' in image_error_message(error.value)
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_chinese_spaces_special_and_long_paths(tmp_path):
    folder = tmp_path / '中文与空格 & [相册]'
    while len(str(folder)) < 290:
        folder /= 'long path segment'
    try:
        folder.mkdir(parents=True)
    except OSError as error:
        pytest.skip(f'当前系统未启用长路径创建：{type(error).__name__}')
    photo = folder / 'IMG20261125120000.jpg'
    Image.new('RGB', (37, 19), '#8395ad').save(photo)
    before = hashlib.sha256(photo.read_bytes()).digest()
    result = scan_library(tmp_path)
    assert not result.error_count and result.items[0].path == photo
    assert read_image(photo).width() == 37
    assert hashlib.sha256(photo.read_bytes()).digest() == before


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows sharing violations')
def test_exclusive_file_lock_is_a_friendly_permission_error(tmp_path):
    photo = tmp_path / 'IMG20261125120000.jpg'
    Image.new('RGB', (37, 19), '#8395ad').save(photo)
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.CreateFileW(str(photo), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != C.c_void_p(-1).value
    try:
        with pytest.raises(PermissionError) as error:
            read_image(photo)
        assert '权限' in image_error_message(error.value)
    finally:
        kernel.CloseHandle(handle)
    assert not read_image(photo).isNull()


def test_missing_and_permission_messages_do_not_crash():
    assert '硬盘' in image_error_message(FileNotFoundError())
    assert '权限' in image_error_message(PermissionError())
    assert '内存' in image_error_message(MemoryError())
