from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget


class CalendarTree(QTreeWidget):
    """Toggle calendar branches with one click anywhere on their row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setExpandsOnDoubleClick(False)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        toggle = (event.button() == Qt.MouseButton.LeftButton
                  and item is not None and item.childCount() > 0)
        expanded = item.isExpanded() if toggle else False
        super().mousePressEvent(event)
        if toggle:
            # Qt may already toggle the small branch arrow during mouse press.
            # Use the original state so both the arrow and label toggle once.
            item.setExpanded(not expanded)

    def mouseDoubleClickEvent(self, event):
        # The first click already toggled the row. Do not toggle it back.
        event.accept()
