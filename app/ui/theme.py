from __future__ import annotations

import ctypes
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


def asset_path(name: str) -> Path:
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return resource_root / "assets" / name


def tokens(dark: bool = False) -> dict[str, str]:
    """Centralized design tokens for the modern minimalist gallery theme."""
    if dark:
        return {
            "bg": "#0e1014",
            "sidebar": "#15181e",
            "surface": "#1c2028",
            "surface_hover": "#232833",
            "surface_subtle": "#171a21",
            "tile_well": "#151820",
            "text": "#f1f3f7",
            "text_secondary": "#a5aebf",
            "muted": "#747e91",
            "border": "#262b36",
            "border_strong": "#373f50",
            "hover": "#232833",
            "selection": "#1c2e4a",
            "accent": "#4f8ff7",
            "accent_hover": "#3a7ce8",
            "accent_pressed": "#2d6cd6",
            "accent_soft": "#192942",
            "accent_border": "#3a5f99",
            "badge_bg": "#1e232d",
            "badge_text": "#a5aebf",
            "banner_bg": "#1d2432",
            "banner_border": "#2e3c54",
            "banner_text": "#c9d6ec",
            "scroll_thumb": "rgba(241, 243, 247, 0.16)",
            "scroll_hover": "rgba(241, 243, 247, 0.30)",
            "check_bg": "#1c2028",
        }
    return {
        "bg": "#f9f9fb",
        "sidebar": "#f2f3f6",
        "surface": "#ffffff",
        "surface_hover": "#f4f6f9",
        "surface_subtle": "#eceef3",
        "tile_well": "#eff1f5",
        "text": "#181a1f",
        "text_secondary": "#5c6370",
        "muted": "#858d9d",
        "border": "#e3e6ed",
        "border_strong": "#cfd5e0",
        "hover": "#e7eaf0",
        "selection": "#e8f0fe",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "accent_pressed": "#1e40af",
        "accent_soft": "#e8f0fe",
        "accent_border": "#93b4f8",
        "badge_bg": "#eceef3",
        "badge_text": "#5c6370",
        "banner_bg": "#eef4ff",
        "banner_border": "#c7dafc",
        "banner_text": "#1e3a6e",
        "scroll_thumb": "rgba(24, 26, 31, 0.16)",
        "scroll_hover": "rgba(24, 26, 31, 0.30)",
        "check_bg": "#ffffff",
    }


@lru_cache(maxsize=128)
def tinted_pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    """Render an SVG asset tinted to an exact color at 2x resolution for crisp HiDPI display."""
    scale = 2
    source = QIcon(str(asset_path(name))).pixmap(QSize(size * scale, size * scale))
    if source.isNull():
        return source
    tinted = QPixmap(source.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    tinted.setDevicePixelRatio(scale)
    return tinted


def tinted_icon(name: str, color: str, size: int = 20) -> QIcon:
    return QIcon(tinted_pixmap(name, color, size))


def apply_window_chrome(widget, dark: bool) -> None:
    """Sync Windows 10/11 native DWM titlebar with the current dark/light theme."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        dwmapi = ctypes.windll.dwmapi
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win11 / Win10 20H1+), fallback 19
        if dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def stylesheet(dark: bool = False) -> str:
    t = tokens(dark)
    arrow = asset_path("chevron-down.svg").as_posix()
    check = asset_path("check.svg").as_posix()
    return f"""
    QWidget {{
        font-family: 'Segoe UI', 'Microsoft YaHei UI';
        font-size: 13px;
        color: {t['text']};
    }}
    QMainWindow, QDialog, QWidget#content {{
        background: {t['bg']};
    }}

    /* Sidebar */
    QFrame#sidebar {{
        background: {t['sidebar']};
        border-right: 1px solid {t['border']};
    }}
    QLabel#brand {{
        font-size: 17px;
        font-weight: 700;
        color: {t['text']};
        letter-spacing: -0.2px;
    }}
    QLabel#brandTagline {{
        font-size: 11.5px;
        color: {t['muted']};
    }}
    QLabel#section {{
        color: {t['muted']};
        font-size: 11px;
        font-weight: 600;
        padding-left: 6px;
    }}
    QFrame#libraryCard {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 12px;
    }}
    QLabel#libraryPath {{
        color: {t['text_secondary']};
        font-size: 11.5px;
    }}
    QLabel#sidebarFooter {{
        color: {t['muted']};
        font-size: 11px;
    }}

    /* Typography */
    QLabel#heading {{
        font-size: 24px;
        font-weight: 700;
        color: {t['text']};
    }}
    QLabel#subtitle {{
        color: {t['badge_text']};
        background: {t['badge_bg']};
        border-radius: 10px;
        padding: 3px 10px;
        font-size: 12px;
        font-weight: 500;
    }}
    QLabel#muted {{
        color: {t['muted']};
        font-size: 12px;
    }}
    QLabel#privacyTitle {{
        font-size: 21px;
        font-weight: 600;
        color: {t['text']};
    }}
    QLabel#emptyTitle {{
        font-size: 21px;
        font-weight: 600;
        color: {t['text']};
    }}

    /* Privacy & Empty State Cards */
    QFrame#privacyCard, QFrame#emptyCard {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 20px;
    }}
    QLabel#emblemBadge {{
        background: {t['accent_soft']};
        border-radius: 34px;
    }}
    QLabel#shortcutHint {{
        color: {t['muted']};
        font-size: 11.5px;
        padding-top: 2px;
    }}

    /* Banner */
    QLabel#banner {{
        background: {t['banner_bg']};
        color: {t['banner_text']};
        border: 1px solid {t['banner_border']};
        border-radius: 10px;
        padding: 9px 14px;
        font-size: 12.5px;
    }}

    /* Base Buttons & Inputs */
    QPushButton, QComboBox {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 8px;
        padding: 6px 12px;
        color: {t['text']};
    }}
    QPushButton:hover, QComboBox:hover {{
        background: {t['surface_hover']};
        border-color: {t['border_strong']};
    }}
    QPushButton:pressed {{
        background: {t['hover']};
    }}
    QPushButton:disabled {{
        color: {t['muted']};
        background: {t['surface_subtle']};
        border-color: {t['border']};
    }}

    /* Primary CTA */
    QPushButton#primary {{
        background: {t['accent']};
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 7px 14px;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{
        background: {t['accent_hover']};
    }}
    QPushButton#primary:pressed {{
        background: {t['accent_pressed']};
    }}
    QPushButton#primary:disabled {{
        background: {t['border_strong']};
        color: {t['muted']};
    }}

    /* Sidebar Privacy Nav Item (borderless pill matching tree items) */
    QPushButton#privacyNavigation {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 7px 10px;
        text-align: left;
        font-weight: 500;
        color: {t['text_secondary']};
    }}
    QPushButton#privacyNavigation:hover {{
        background: {t['hover']};
        color: {t['text']};
    }}
    QPushButton#privacyNavigation:checked {{
        background: {t['selection']};
        color: {t['accent']};
        font-weight: 600;
        border-color: transparent;
    }}

    /* Header Action Pills */
    QPushButton#headerPill {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 8px;
        padding: 5px 11px;
        font-size: 12.5px;
        font-weight: 500;
        color: {t['text_secondary']};
    }}
    QPushButton#headerPill:hover {{
        background: {t['surface_hover']};
        border-color: {t['border_strong']};
        color: {t['text']};
    }}
    QPushButton#headerPill:checked {{
        background: {t['selection']};
        color: {t['accent']};
        border-color: {t['accent_border']};
        font-weight: 600;
    }}

    /* Ghost / Compact Icon Buttons */
    QPushButton#ghostButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 4px 8px;
        font-size: 11.5px;
        color: {t['muted']};
    }}
    QPushButton#ghostButton:hover {{
        background: {t['hover']};
        color: {t['text']};
    }}
    QPushButton#cardAction {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 3px 7px;
        font-size: 11.5px;
        color: {t['text_secondary']};
    }}
    QPushButton#cardAction:hover {{
        background: {t['hover']};
        color: {t['text']};
    }}
    QPushButton#cardAction:disabled {{
        background: transparent;
        border-color: transparent;
        color: {t['muted']};
    }}

    /* Back Button */
    QPushButton#backButton {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 8px;
        padding: 5px 12px 5px 8px;
        font-size: 12.5px;
        font-weight: 600;
        color: {t['text']};
    }}
    QPushButton#backButton:hover {{
        background: {t['surface_hover']};
        border-color: {t['border_strong']};
    }}
    QPushButton#backButton:pressed {{
        background: {t['hover']};
    }}
    QPushButton#backButton:focus {{
        border-color: {t['accent']};
    }}

    /* Segmented Fit/Cover Control */
    QFrame#segmentedControl {{
        background: {t['surface_subtle']};
        border: 1px solid {t['border']};
        border-radius: 8px;
    }}
    QPushButton#segmentButton {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 500;
        color: {t['text_secondary']};
    }}
    QPushButton#segmentButton:hover {{
        color: {t['text']};
    }}
    QPushButton#segmentButton:checked {{
        background: {t['surface']};
        color: {t['text']};
        font-weight: 600;
    }}

    /* Sidebar Toggle */
    QToolButton#sidebarToggle {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 0;
    }}
    QToolButton#sidebarToggle:hover {{
        background: {t['hover']};
    }}
    QToolButton#sidebarToggle:pressed {{
        background: {t['selection']};
    }}
    QToolButton#sidebarToggle:focus {{
        border: 1px solid {t['accent']};
    }}

    /* ComboBox & Popup */
    QComboBox {{
        min-width: 96px;
        padding: 5px 26px 5px 11px;
        font-size: 12.5px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: url("{arrow}");
        width: 13px;
        height: 13px;
    }}
    QComboBox QAbstractItemView, QListView#sortPopup {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 8px;
        padding: 4px;
        outline: none;
        selection-background-color: {t['selection']};
        selection-color: {t['text']};
    }}
    QListView#sortPopup::item {{
        min-height: 30px;
        padding: 5px 10px;
        border-radius: 6px;
    }}
    QListView#sortPopup::item:selected {{
        background: {t['selection']};
        color: {t['accent']};
        font-weight: 600;
    }}

    /* Navigation Tree */
    QTreeWidget {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QTreeWidget::item {{
        background: transparent;
        border: none;
    }}
    QTreeWidget::branch {{
        background: transparent;
        border: none;
    }}

    /* Grid & List Views */
    QListView {{
        border: none;
        background: transparent;
        outline: none;
    }}

    /* Modern Thin Scrollbars */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t['scroll_thumb']};
        border-radius: 4px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t['scroll_hover']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0;
        border: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 0 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['scroll_thumb']};
        border-radius: 4px;
        min-width: 32px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {t['scroll_hover']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
        width: 0;
        border: none;
    }}

    /* CheckBox */
    QCheckBox {{
        spacing: 7px;
        color: {t['text_secondary']};
        font-size: 12px;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border-radius: 4px;
        border: 1.5px solid {t['border_strong']};
        background: {t['check_bg']};
    }}
    QCheckBox::indicator:hover {{
        border-color: {t['accent']};
    }}
    QCheckBox::indicator:checked {{
        background: {t['accent']};
        border-color: {t['accent']};
        image: url("{check}");
    }}

    /* Slider with active fill */
    QSlider::groove:horizontal {{
        height: 4px;
        background: {t['border']};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {t['accent']};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -5px 0;
        background: {t['surface']};
        border: 2px solid {t['accent']};
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {t['accent']};
    }}

    /* StatusBar & Progress */
    QStatusBar {{
        background: {t['bg']};
        color: {t['muted']};
        border-top: 1px solid {t['border']};
        font-size: 12px;
        padding: 2px 12px;
    }}
    QStatusBar::item {{
        border: none;
    }}
    QProgressBar {{
        border: none;
        background: {t['border']};
        border-radius: 3px;
        height: 5px;
    }}
    QProgressBar::chunk {{
        background: {t['accent']};
        border-radius: 3px;
    }}
    QToolTip {{
        background: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border_strong']};
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 12px;
    }}
    """


def viewer_stylesheet() -> str:
    """Dedicated immersive dark cinema stylesheet for the photo & video lightbox."""
    return """
    QDialog#photoViewer {
        background: #0b0d11;
        color: #f1f3f7;
        font-family: 'Segoe UI', 'Microsoft YaHei UI';
        font-size: 13px;
    }
    QFrame#viewerTopBar {
        background: #12151c;
        border-bottom: 1px solid #1f2430;
    }
    QFrame#viewerBottomBar {
        background: #12151c;
        border-top: 1px solid #1f2430;
    }
    QLabel#viewerTitle {
        color: #f1f3f7;
        font-size: 14px;
        font-weight: 600;
    }
    QLabel#viewerInfo {
        color: #98a2b3;
        font-size: 12.5px;
    }
    QLabel#viewerMessage {
        color: #98a2b3;
        background: #0b0d11;
        font-size: 14px;
    }
    QPushButton#viewerNavigation, QPushButton#viewerTool {
        background: #1a1e28;
        color: #e2e8f0;
        border: 1px solid #282f3f;
        border-radius: 8px;
        padding: 5px 12px;
        font-size: 12.5px;
        font-weight: 500;
    }
    QPushButton#viewerNavigation:hover, QPushButton#viewerTool:hover {
        background: #252b39;
        border-color: #3a4459;
        color: #ffffff;
    }
    QPushButton#viewerNavigation:pressed, QPushButton#viewerTool:pressed {
        background: #2f374a;
    }
    QPushButton#viewerNavigation:disabled, QPushButton#viewerTool:disabled {
        background: #141720;
        border-color: #1d222e;
        color: #525c70;
    }
    QPushButton#viewerClose {
        background: #1a1e28;
        color: #cbd5e1;
        border: 1px solid #282f3f;
        border-radius: 8px;
        padding: 5px 12px;
        font-size: 12.5px;
        font-weight: 500;
    }
    QPushButton#viewerClose:hover {
        background: #3b1d24;
        border-color: #7f2938;
        color: #fecdd3;
    }
    QWidget#videoPlayer {
        background: #0b0d11;
    }
    QFrame#videoControlBar {
        background: #151922;
        border: 1px solid #222836;
        border-radius: 12px;
    }
    QLabel#videoStatus {
        background: #1b2230;
        color: #cbd5e1;
        border: 1px solid #2b354a;
        border-radius: 8px;
        padding: 7px 12px;
        font-size: 12.5px;
    }
    QLabel#videoTime {
        color: #cbd5e1;
        font-size: 12px;
        font-family: 'Segoe UI', 'Microsoft YaHei UI';
    }
    QPushButton#videoPlayButton {
        background: #2563eb;
        color: #ffffff;
        border: none;
        border-radius: 8px;
        padding: 5px 13px;
        font-size: 12.5px;
        font-weight: 600;
    }
    QPushButton#videoPlayButton:hover {
        background: #3b82f6;
    }
    QPushButton#videoPlayButton:disabled {
        background: #252b38;
        color: #64748b;
    }
    QSlider#videoScrub::groove:horizontal, QSlider#videoVolume::groove:horizontal {
        height: 4px;
        background: #2a3142;
        border-radius: 2px;
    }
    QSlider#videoScrub::sub-page:horizontal, QSlider#videoVolume::sub-page:horizontal {
        background: #4f8ff7;
        border-radius: 2px;
    }
    QSlider#videoScrub::handle:horizontal, QSlider#videoVolume::handle:horizontal {
        width: 13px;
        height: 13px;
        margin: -4.5px 0;
        background: #ffffff;
        border: 2px solid #4f8ff7;
        border-radius: 6.5px;
    }
    QSlider#videoScrub::handle:horizontal:hover, QSlider#videoVolume::handle:horizontal:hover {
        background: #ffffff;
        border-color: #93c5fd;
    }
    QToolTip {
        background: #1c2028;
        color: #f1f3f7;
        border: 1px solid #373f50;
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 12px;
    }
    """
