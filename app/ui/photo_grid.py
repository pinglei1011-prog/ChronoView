from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyle

from app.core.library import MediaItem
from app.services.thumbnail_service import ThumbnailService


class MediaModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[MediaItem] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.path.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{item.path}\n{item.date_label}\n{'视频' if item.kind == 'video' else '照片'}"
        if role == Qt.ItemDataRole.UserRole:
            return item
        return None

    def replace(self, items: list[MediaItem]):
        self.beginResetModel()
        self.items = items
        self.endResetModel()


class MediaDelegate(QStyledItemDelegate):
    def __init__(self, thumbnails: ThumbnailService, parent=None):
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.edge = 180
        self.dark = False

    def sizeHint(self, option, index):
        return QSize(self.edge + 16, self.edge + 53)

    def paint(self, painter: QPainter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        outer = QRectF(option.rect).adjusted(3, 3, -3, -3)
        if selected:
            painter.setBrush(QColor("#243d59" if self.dark else "#e4efff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(outer, 12, 12)
        box = QRectF(option.rect.x() + 8, option.rect.y() + 8, self.edge, self.edge)
        clip = QPainterPath()
        clip.addRoundedRect(box, 10, 10)
        painter.setClipPath(clip)
        painter.fillRect(box, QColor("#252c37" if self.dark else "#e9edf4"))
        pixmap, error = self.thumbnails.get(item)
        if pixmap is not None and not pixmap.isNull():
            # Fit rather than stretch or crop: preserve the entire photo and its aspect ratio.
            size = pixmap.size().scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(box.center().x() - size.width() / 2,
                            box.center().y() - size.height() / 2, size.width(), size.height())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(target.toRect(), pixmap)
        else:
            painter.setPen(QColor("#91a0b7"))
            font = QFont("Segoe UI", 12)
            painter.setFont(font)
            text = "无法读取\n双击查看详情" if error and item.kind == "image" else "正在加载…"
            if item.kind == "video":
                text = f"视频\n{item.path.suffix.upper().lstrip('.')}"
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.setClipping(False)
        if item.kind == "video":
            badge = QRectF(box.left() + 9, box.top() + 9, 29, 25)
            painter.setBrush(QColor(20, 27, 40, 180))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, 7, 7)
            painter.setBrush(QColor("#ffffff"))
            painter.drawPolygon(QPolygonF([QPointF(badge.x() + 11, badge.y() + 6),
                                          QPointF(badge.x() + 11, badge.y() + 19),
                                          QPointF(badge.x() + 21, badge.y() + 12.5)]))
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#4389f5"), 2))
            painter.drawRoundedRect(box, 10, 10)
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("#dce4ef" if self.dark else "#38465b"))
        label_box = option.rect.adjusted(9, self.edge + 15, -9, -17)
        name = painter.fontMetrics().elidedText(item.path.name, Qt.TextElideMode.ElideMiddle, label_box.width())
        painter.drawText(label_box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#95a3b8" if self.dark else "#8490a2"))
        date_box = option.rect.adjusted(9, self.edge + 33, -9, 0)
        painter.drawText(date_box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         item.taken_at.strftime("%Y.%m.%d  %H:%M") if item.taken_at else "未识别日期")
        painter.restore()


class PhotoGrid(QListView):
    def __init__(self, thumbnails: ThumbnailService, parent=None):
        super().__init__(parent)
        self.media_model = MediaModel(self)
        self.delegate = MediaDelegate(thumbnails, self)
        self.setModel(self.media_model)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(128)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setWordWrap(False)
        self.setSpacing(0)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setSingleShot(True)
        self.repaint_timer.setInterval(35)
        self.repaint_timer.timeout.connect(self.viewport().update)
        thumbnails.updated.connect(self.schedule_repaint)
        self.requested_edge = 180
        self.set_thumbnail_size(180)

    def schedule_repaint(self, _key):
        if not self.repaint_timer.isActive():
            self.repaint_timer.start()

    def set_thumbnail_size(self, edge: int):
        self.requested_edge = edge
        self.fit_columns()

    def fit_columns(self):
        width = max(1, self.viewport().width())
        columns = max(1, round(width / (self.requested_edge + 16)))
        edge = max(64, width // columns - 16)
        self.delegate.edge = edge
        self.setGridSize(QSize(edge + 16, edge + 53))
        self.doItemsLayout()
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "requested_edge"):
            self.fit_columns()
