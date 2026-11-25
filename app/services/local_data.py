"""Explicit, asynchronous deletion of application records (never source media)."""
from PySide6.QtCore import QThread, Signal
from app.storage.index import LibraryIndex
from app.services.local_logs import clear_logs


class ClearLocalData(QThread):
    completed = Signal(str)

    def __init__(self, index_path, parent=None):
        super().__init__(parent)
        self.index_path = index_path

    def run(self):
        error = ""
        try:
            LibraryIndex(self.index_path).clear()
            clear_logs()
        except Exception:
            error = "本地记录未能全部清除，请关闭其他实例后重试。"
        self.completed.emit(error)
