from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyle

from app.core.library import MediaItem
from app.services.thumbnail_service import ThumbnailService, cache_key
from app.services.video_thumbnail import format_duration
from app.ui.grid_layout import grid_layout_width


class MediaModel(QAbstractListModel):
    def __init__(self, parent=None, thumbnails=None):
        super().__init__(parent)
        self.items: list[MediaItem] = []
        self.thumbnails = thumbnails

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.path.name
        if role == Qt.ItemDataRole.ToolTipRole:
            error = ""
            if self.thumbnails:
                error = self.thumbnails.memory.get(cache_key(item), (None, ""))[1]
            return f"{item.path}\n{item.date_label}\n{'视频' if item.kind == 'video' else '照片'}" + (f"\n\n{error}" if error else "")
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
        return QSize(self.edge + 16, self.edge + 36)

    def paint(self, painter: QPainter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        outer = QRectF(option.rect).adjusted(3, 3, -3, -3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1c2028" if self.dark else "#ffffff"))
        painter.drawRoundedRect(outer, 16, 16)
        if selected:
            painter.setBrush(QColor("#243d59" if self.dark else "#e4efff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(outer, 12, 12)
        box = QRectF(option.rect.x() + 8, option.rect.y() + 8, self.edge, self.edge)
        clip = QPainterPath()
        clip.addRoundedRect(box, 14, 14)
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
            text = "无法读取\n打开查看详情" if error else "正在加载…"
            if item.kind == "video":
                text = "无法读取视频\n点击查看详情" if error else "正在提取封面…"
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.setClipping(False)
        if item.kind == "video":
            if pixmap is not None and not pixmap.isNull():
                diameter = min(52, box.width() * .3)
                center = box.center()
                painter.setBrush(QColor(20, 27, 40, 185))
                painter.setPen(QPen(QColor(255, 255, 255, 100), 1))
                painter.drawEllipse(center, diameter / 2, diameter / 2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#ffffff"))
                painter.drawPolygon(QPolygonF([QPointF(center.x() - diameter * .12, center.y() - diameter * .2),
                                              QPointF(center.x() - diameter * .12, center.y() + diameter * .2),
                                              QPointF(center.x() + diameter * .24, center.y())]))
            duration = self.thumbnails.duration(item)
            if duration:
                duration_box = QRectF(box.right() - 74, box.bottom() - 32, 65, 24)
                painter.setBrush(QColor(20, 27, 40, 195))
                painter.drawRoundedRect(duration_box, 6, 6)
                painter.setPen(QColor("white"))
                painter.setFont(QFont("Segoe UI", 9))
                painter.drawText(duration_box, Qt.AlignmentFlag.AlignCenter, format_duration(duration))
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#4389f5"), 2))
            painter.drawRoundedRect(box, 10, 10)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#95a3b8" if self.dark else "#8490a2"))
        date_box = option.rect.adjusted(9, self.edge + 14, -9, -5)
        painter.drawText(date_box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         item.taken_at.strftime("%Y.%m.%d  %H:%M") if item.taken_at else "未识别日期")
        painter.restore()


class PhotoGrid(QListView):
    def __init__(self, thumbnails: ThumbnailService, parent=None):
        super().__init__(parent)
        self.media_model = MediaModel(self, thumbnails)
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
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setSingleShot(True)
        self.repaint_timer.setInterval(35)
        self.repaint_timer.timeout.connect(self.viewport().update)
        thumbnails.updated.connect(self.schedule_repaint)
        self.reflow_timer = QTimer(self)
        self.reflow_timer.setSingleShot(True)
        self.reflow_timer.setInterval(0)
        self.reflow_timer.timeout.connect(self._fit_columns)
        self.requested_edge = 180
        self.set_thumbnail_size(180)

    def schedule_repaint(self, _key):
        if not self.repaint_timer.isActive():
            self.repaint_timer.start()

    def set_thumbnail_size(self, edge: int):
        self.requested_edge = edge
        self.fit_columns()

    def fit_columns(self):
        self.reflow_timer.start()

    def _fit_columns(self):
        width = grid_layout_width(self)
        columns = max(1, round(width / (self.requested_edge + 16)))
        edge = max(64, width // columns - 16)
        self.delegate.edge = edge
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
