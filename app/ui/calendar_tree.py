from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyle, QStyleFactory, QStyledItemDelegate, QTreeWidget

from app.ui.theme import tinted_pixmap, tokens


class CalendarItemDelegate(QStyledItemDelegate):
    """Paints clean gallery sidebar items with right-aligned tabular count badges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dark = False

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QSize(base.width(), 34)

    def paint(self, painter: QPainter, option, index):
        t = tokens(self.dark)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        route = index.data(Qt.ItemDataRole.UserRole)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        label, count = (text.split("  ·  ", 1) if "  ·  " in text else (text, ""))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pill = QRectF(option.rect).adjusted(0, 2, -2, -2)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["selection"]))
            painter.drawRoundedRect(pill, 8, 8)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["hover"]))
            painter.drawRoundedRect(pill, 8, 8)

        is_root = route == ("all",)
        is_month = isinstance(route, tuple) and len(route) > 0 and route[0] == "month"
        font = QFont(option.font)
        font.setPointSizeF(9.5 if not is_month else 9.0)
        font.setWeight(QFont.Weight.DemiBold if (selected or is_root) else QFont.Weight.Normal)
        painter.setFont(font)

        text_color = t["accent"] if selected else (t["text"] if not is_month else t["text_secondary"])
        painter.setPen(QColor(text_color))

        right_pad = 10
        count_width = 0
        if count:
            count_font = QFont(option.font)
            count_font.setPointSizeF(8.5)
            count_font.setWeight(QFont.Weight.Medium if selected else QFont.Weight.Normal)
            painter.setFont(count_font)
            fm = painter.fontMetrics()
            count_width = fm.horizontalAdvance(count) + 14
            badge_rect = QRectF(pill.right() - count_width - 4, pill.center().y() - 9.5, count_width, 19)
            if selected:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(t["accent"]))
                painter.setOpacity(0.14)
                painter.drawRoundedRect(badge_rect, 9.5, 9.5)
                painter.setOpacity(1.0)
                painter.setPen(QColor(t["accent"]))
            else:
                painter.setPen(QColor(t["muted"]))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, count)
            painter.setFont(font)
            painter.setPen(QColor(text_color))
            right_pad = count_width + 10

        label_rect = QRectF(pill.left() + 8, pill.top(), max(10.0, pill.width() - 8 - right_pad), pill.height())
        elided = painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(label_rect.width()))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        painter.restore()


class CalendarTree(QTreeWidget):
    """Toggle calendar branches with one click anywhere on their row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setExpandsOnDoubleClick(False)
        self.setMouseTracking(True)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            self.setStyle(fusion)
        self.delegate = CalendarItemDelegate(self)
        self.setItemDelegate(self.delegate)

    def drawBranches(self, painter: QPainter, rect, index):
        t = tokens(self.delegate.dark)
        painter.fillRect(rect, QColor(t["sidebar"]))
        if not self.model().hasChildren(index):
            return
        selected = self.selectionModel().isSelected(index) if self.selectionModel() else False
        icon_name = "tree-down.svg" if self.isExpanded(index) else "tree-right.svg"
        color = t["accent"] if selected else t["muted"]
        pixmap = tinted_pixmap(icon_name, color, 14)
        if pixmap.isNull():
            return
        size = 14
        indent = self.indentation()
        # Draw chevron in the branch column immediately adjacent to this item's label
        x = rect.right() - indent + (indent - size) // 2 + 1
        y = rect.top() + (rect.height() - size) // 2
        painter.drawPixmap(int(x), int(y), pixmap)

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
