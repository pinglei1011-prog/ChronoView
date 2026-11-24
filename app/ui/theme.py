def stylesheet(dark: bool = False) -> str:
    bg, panel, text, muted, border, hover, selection = (
        ("#14171d", "#1c2028", "#edf0f6", "#9aa6b8", "#2b3341", "#292f3b", "#243d59") if dark else
        ("#f5f6fa", "#ffffff", "#202b3a", "#758195", "#e5e9f0", "#edf2fa", "#e4efff")
    )
    return f"""
    QWidget {{ font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; color: {text}; }}
    QMainWindow, QDialog, QWidget#content {{ background: {bg}; }}
    QFrame#sidebar {{ background: {panel}; border-right: 1px solid {border}; }}
    QLabel#brand {{ font-size: 25px; font-weight: 700; color: #4389f5; }}
    QLabel#heading {{ font-size: 29px; font-weight: 700; }}
    QLabel#muted, QLabel#subtitle {{ color: {muted}; }}
    QLabel#section {{ color: {muted}; font-size: 11px; font-weight: 600; }}
    QLabel#emptyTitle {{ font-size: 24px; font-weight: 600; }}
    QPushButton, QComboBox {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; padding: 8px 13px; }}
    QPushButton:hover, QComboBox:hover {{ background: {hover}; }}
    QPushButton:disabled {{ color: {muted}; }}
    QComboBox {{ min-width: 100px; padding-right: 24px; }}
    QComboBox::drop-down {{ border: none; width: 22px; background: transparent; }}
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
