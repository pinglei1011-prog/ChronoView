from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from app.core.albums import Album
from app.ui.grid_layout import grid_layout_width
from app.ui.theme import tokens


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
        return QSize(self.edge + 16, 134)

    def paint(self, painter: QPainter, option, index):
        album = index.data(Qt.ItemDataRole.UserRole)
        if album is None:
            return
        t = tokens(self.dark)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        card = QRectF(option.rect).adjusted(7, 7, -7, -7)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        bg = t["selection"] if selected else (t["surface_hover"] if hovered else t["surface"])
        border_color = t["accent"] if selected else (t["accent_border"] if hovered else t["border"])
        painter.setBrush(QColor(bg))
        painter.setPen(QPen(QColor(border_color), 1.5 if selected else 1.0))
        painter.drawRoundedRect(card, 14, 14)

        total = album.photos + album.videos
        pad_x = 18.0
        inner_w = card.width() - pad_x * 2

        # Top-right total count pill
        pill_text = f"{total:,} 项"
        pill_font = QFont("Segoe UI", 8.5)
        pill_font.setWeight(QFont.Weight.Medium)
        painter.setFont(pill_font)
        fm = painter.fontMetrics()
        pill_w = fm.horizontalAdvance(pill_text) + 16
        pill_rect = QRectF(card.right() - pad_x - pill_w, card.top() + 18, pill_w, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["accent_soft"] if (hovered or selected) else t["badge_bg"]))
        painter.drawRoundedRect(pill_rect, 11, 11)
        painter.setPen(QColor(t["accent"] if (hovered or selected) else t["badge_text"]))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, pill_text)

        # Month / Year title
        title_font = QFont("Segoe UI", 16 if album.route[0] == "unknown" else 19, QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(t["text"]))
        title_rect = QRectF(card.left() + pad_x, card.top() + 14, max(40.0, inner_w - pill_w - 10), 32)
        title_text = painter.fontMetrics().elidedText(album.title, Qt.TextElideMode.ElideRight, int(title_rect.width()))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title_text)

        # Photo / Video breakdown
        sub_font = QFont("Segoe UI", 9)
        painter.setFont(sub_font)
        painter.setPen(QColor(t["text_secondary"]))
        sub_rect = QRectF(card.left() + pad_x, title_rect.bottom() + 4, inner_w, 20)
        sub_text = painter.fontMetrics().elidedText(album.subtitle, Qt.TextElideMode.ElideRight, int(sub_rect.width()))
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sub_text)

        # Visual proportion bar (photos in accent blue, videos in teal-indigo)
        bar_rect = QRectF(card.left() + pad_x, sub_rect.bottom() + 10, inner_w, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["surface_subtle"]))
        painter.drawRoundedRect(bar_rect, 2, 2)
        if total > 0:
            photo_ratio = album.photos / total
            video_ratio = album.videos / total
            gap = 2.0 if (album.photos > 0 and album.videos > 0) else 0.0
            avail = max(0.0, bar_rect.width() - gap)
            if album.photos > 0:
                pw = max(4.0, avail * photo_ratio)
                painter.setBrush(QColor(t["accent"]))
                painter.drawRoundedRect(QRectF(bar_rect.left(), bar_rect.top(), pw, bar_rect.height()), 2, 2)
            if album.videos > 0:
                vw = max(4.0, avail * video_ratio)
                vx = bar_rect.right() - vw
                painter.setBrush(QColor("#8b5cf6" if self.dark else "#7c3aed"))
                painter.drawRoundedRect(QRectF(vx, bar_rect.top(), vw, bar_rect.height()), 2, 2)

        # Subtle footer prompt + chevron
        detail_font = QFont("Segoe UI", 8.5)
        detail_font.setWeight(QFont.Weight.Medium if (hovered or selected) else QFont.Weight.Normal)
        painter.setFont(detail_font)
        painter.setPen(QColor(t["accent"] if (hovered or selected) else t["muted"]))
        detail_rect = QRectF(card.left() + pad_x, card.bottom() - 28, inner_w, 20)
        prompt = f"{album.months} 个月" if album.route[0] == "year" else "查看当月媒体"
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, prompt)
        chevron_font = QFont("Segoe UI", 12)
        painter.setFont(chevron_font)
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "›")
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
        columns = max(1, round(width / (self.requested_edge + 16)))
        self.delegate.edge = max(120, width // columns - 16)
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
