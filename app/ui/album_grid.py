from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyle

from app.core.albums import Album
from app.ui.grid_layout import grid_layout_width


class AlbumModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[Album] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        album = self.items[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return album
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{album.title} · {album.subtitle}"
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{album.title}\n{album.subtitle}\n点击浏览{'月份' if album.route[0] == 'year' else '照片与视频'}"
        return None

    def replace(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()


class AlbumDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.edge = 240
        self.dark = False

    def sizeHint(self, option, index):
        return QSize(self.edge + 20, 156)

    def paint(self, painter: QPainter, option, index):
        album = index.data(Qt.ItemDataRole.UserRole)
        if album is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(8, 8, -8, -8)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        background = ("#243d59" if self.dark else "#e4efff") if selected else (
            ("#232b37" if self.dark else "#eef4fd") if hovered else
            ("#1c2028" if self.dark else "#ffffff"))
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor("#4389f5" if selected else ("#2b3341" if self.dark else "#e5e9f0")), 1))
        painter.drawRoundedRect(card, 16, 16)
        painter.setPen(QColor("#edf0f6" if self.dark else "#202b3a"))
        painter.setFont(QFont("Segoe UI", 18 if album.route[0] == "unknown" else 22, QFont.Weight.DemiBold))
        title = QRectF(card.x() + 18, card.y() + 16, card.width() - 36, 42)
        title_text = painter.fontMetrics().elidedText(album.title, Qt.TextElideMode.ElideRight, int(title.width()))
        painter.drawText(title, Qt.AlignmentFlag.AlignVCenter, title_text)
        painter.setPen(QColor("#9aa6b8" if self.dark else "#758195"))
        painter.setFont(QFont("Segoe UI", 9))
        subtitle = QRectF(title.x(), title.bottom() + 5, title.width(), 22)
        text = painter.fontMetrics().elidedText(album.subtitle, Qt.TextElideMode.ElideRight, int(subtitle.width()))
        painter.drawText(subtitle, Qt.AlignmentFlag.AlignVCenter, text)
        detail = QRectF(title.x(), card.bottom() - 34, title.width(), 22)
        painter.setPen(QColor("#7ca7e8" if self.dark else "#4f79ae"))
        painter.drawText(detail, Qt.AlignmentFlag.AlignVCenter,
                         f"{album.months} 个月" if album.route[0] == "year" else "查看照片与视频")
        painter.drawText(detail, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "›")
        painter.restore()


class AlbumGrid(QListView):
    opened = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.album_model = AlbumModel(self)
        self.delegate = AlbumDelegate(self)
        self.setModel(self.album_model)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setWordWrap(False)
        self.setSpacing(0)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.clicked.connect(self.open_index)
        for key in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key), self, activated=lambda: self.open_index(self.currentIndex()))
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.requested_edge = 240
        self.reflow_timer = QTimer(self)
        self.reflow_timer.setSingleShot(True)
        self.reflow_timer.setInterval(0)
        self.reflow_timer.timeout.connect(self._fit_columns)
        self.fit_columns()

    def open_index(self, index):
        if index.isValid():
            album = index.data(Qt.ItemDataRole.UserRole)
            self.opened.emit(album.route)

    def set_thumbnail_size(self, edge):
        self.requested_edge = max(180, edge + 60)
        self.fit_columns()

    def fit_columns(self):
        self.reflow_timer.start()

    def _fit_columns(self):
        width = grid_layout_width(self)
        columns = max(1, round(width / (self.requested_edge + 20)))
        self.delegate.edge = max(100, width // columns - 20)
        size = self.delegate.sizeHint(None, None)
        if self.gridSize() != size:
            self.setGridSize(size)
            self.doItemsLayout()
        self.viewport().update()

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.Resize and hasattr(self, "reflow_timer"):
            self.fit_columns()
        return super().viewportEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_columns()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "requested_edge"):
            self.fit_columns()
