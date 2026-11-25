"""Supply neutral Windows taskbar thumbnails while the window is private."""
import ctypes as C
from ctypes import wintypes as W
import sys


def set_private_preview(widget, private):
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = C.c_int(bool(private))
        for attribute in (7, 10, 11, 12):
            C.windll.dwmapi.DwmSetWindowAttribute(W.HWND(hwnd), attribute, C.byref(value), 4)
        C.windll.dwmapi.DwmInvalidateIconicBitmaps(W.HWND(hwnd))
    except OSError:
        pass


def handle_private_preview(widget, message):
    if sys.platform != "win32":
        return False
    msg = W.MSG.from_address(int(message))
    if msg.message not in (0x323, 0x326):
        return False
    width = max(1, min(1024, (msg.lParam >> 16) & 0xffff)) if msg.message == 0x323 else max(1, min(1024, widget.width()))
    height = max(1, min(768, msg.lParam & 0xffff)) if msg.message == 0x323 else max(1, min(768, widget.height()))
    # A 32-bit device-dependent bitmap, containing only a solid neutral surface.
    pixels = C.create_string_buffer(bytes((30, 24, 21, 255)) * width * height)
    gdi = C.windll.gdi32
    gdi.CreateBitmap.argtypes = [C.c_int, C.c_int, W.UINT, W.UINT, C.c_void_p]
    gdi.CreateBitmap.restype = W.HBITMAP
    bitmap = gdi.CreateBitmap(width, height, 1, 32, pixels)
    if bitmap:
        try:
            if msg.message == 0x323:
                C.windll.dwmapi.DwmSetIconicThumbnail(W.HWND(int(widget.winId())), W.HBITMAP(bitmap), 0)
            else:
                C.windll.dwmapi.DwmSetIconicLivePreviewBitmap(W.HWND(int(widget.winId())), W.HBITMAP(bitmap), None, 0)
        finally:
            gdi.DeleteObject(W.HGDIOBJ(bitmap))
    return True
