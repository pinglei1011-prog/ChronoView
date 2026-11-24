import sys
from pathlib import Path


def asset_path(name: str) -> Path:
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return resource_root / "assets" / name


def stylesheet(dark: bool = False) -> str:
    arrow = asset_path("chevron-down.svg").as_posix()
    bg, panel, text, muted, border, hover, selection = (
        ("#14171d", "#1c2028", "#edf0f6", "#9aa6b8", "#2b3341", "#292f3b", "#243d59") if dark else
        ("#f5f6fa", "#ffffff", "#202b3a", "#758195", "#e5e9f0", "#edf2fa", "#e4efff")
    )
    return f"""
    QWidget {{ font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; color: {text}; }}
    QMainWindow, QDialog, QWidget#content {{ background: {bg}; }}
    QFrame#sidebar {{ background: {panel}; border-right: 1px solid {border}; }}
    QLabel#privacyTitle {{ font-size: 24px; font-weight: 600; }}
    QLabel#brand {{ font-size: 25px; font-weight: 700; color: #4389f5; }}
    QLabel#heading {{ font-size: 29px; font-weight: 700; }}
    QLabel#muted, QLabel#subtitle {{ color: {muted}; }}
    QLabel#section {{ color: {muted}; font-size: 11px; font-weight: 600; }}
    QLabel#emptyTitle {{ font-size: 24px; font-weight: 600; }}
    QPushButton, QComboBox {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; padding: 8px 13px; }}
    QPushButton:hover, QComboBox:hover {{ background: {hover}; }}
    QPushButton#privacyNavigation {{ border: 1px solid {border}; text-align: left; }}
    QPushButton#privacyNavigation:checked {{ background: {selection}; color: #4389f5; border-color: #8cb5f3; }}
    QPushButton#backButton {{ border-radius: 10px; padding: 6px 14px 6px 10px; font-weight: 600; }}
    QPushButton#backButton:hover {{ background: {selection}; border-color: #8cb5f3; }}
    QPushButton#backButton:pressed {{ background: {selection}; border-color: #4389f5; }}
    QPushButton#backButton:focus {{ border-color: #4389f5; }}
    QPushButton#viewerNavigation {{ border-radius: 10px; padding: 6px 10px; font-weight: 600; }}
    QPushButton#viewerNavigation:hover {{ background: {selection}; border-color: #8cb5f3; }}
    QPushButton#viewerNavigation:pressed {{ background: {selection}; border-color: #4389f5; }}
    QPushButton#viewerNavigation:focus {{ border-color: #4389f5; }}
    QToolButton#sidebarToggle {{ background: transparent; border: none; border-radius: 8px; padding: 0; }}
    QToolButton#sidebarToggle:hover {{ background: {hover}; }}
    QToolButton#sidebarToggle:pressed {{ background: {selection}; }}
    QToolButton#sidebarToggle:focus {{ border: 1px solid #4389f5; }}
    QPushButton:disabled {{ color: {muted}; }}
    QComboBox {{ min-width: 100px; padding-right: 24px; }}
    QComboBox::drop-down {{ border: none; width: 22px; background: transparent; }}
    QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView, QListView#sortPopup {{
        background-color: {panel}; color: {text}; border: 1px solid {border};
        padding: 4px; outline: none; selection-background-color: {selection}; selection-color: {text};
    }}
    QListView#sortPopup::item {{ min-height: 30px; padding: 5px 10px; border-radius: 5px; }}
    QListView#sortPopup::item:selected {{ background: {selection}; color: {text}; }}
    QPushButton#primary {{ background: #327cf1; color: white; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: #2168d5; }}
    QTreeWidget {{ background: transparent; border: none; outline: none; }}
    QTreeWidget::item {{ padding: 7px 2px; border-radius: 7px; }}
    QTreeWidget::item:selected {{ background: {selection}; color: #4389f5; }}
    QTreeWidget::item:hover {{ background: {hover}; }}
    QListView {{ border: none; background: transparent; outline: none; }}
    QStatusBar {{ background: {panel}; color: {muted}; border-top: 1px solid {border}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 13px; margin: -5px 0; background: #4389f5; border-radius: 6px; }}
    QProgressBar {{ border: none; background: {border}; border-radius: 3px; height: 5px; }}
    QProgressBar::chunk {{ background: #4389f5; border-radius: 3px; }}
    QToolTip {{ background: {panel}; border: 1px solid {border}; padding: 6px; }}
    """
