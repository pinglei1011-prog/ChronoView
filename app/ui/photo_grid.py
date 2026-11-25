from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate

from app.core.library import MediaItem
from app.services.thumbnail_service import ThumbnailService, cache_key
from app.services.video_thumbnail import format_duration
from app.ui.grid_layout import grid_layout_width
from app.ui.theme import tokens


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
        self.crop_mode = False

    def sizeHint(self, option, index):
        return QSize(self.edge + 14, self.edge + 34)

    def paint(self, painter: QPainter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            return
        t = tokens(self.dark)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        box = QRectF(option.rect.x() + 7, option.rect.y() + 6, self.edge, self.edge)
        radius = 10.0

        # Subtle hover/selected backdrop halo instead of heavy double-nested card frames
        if selected or hovered:
            halo = box.adjusted(-3, -3, 3, 24)
            painter.setPen(Qt.PenStyle.NoPen)
            halo_color = QColor(t["selection"] if selected else t["hover"])
            halo_color.setAlpha(180 if selected else 110)
            painter.setBrush(halo_color)
            painter.drawRoundedRect(halo, 13, 13)

        clip = QPainterPath()
        clip.addRoundedRect(box, radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(box, QColor(t["tile_well"]))

        pixmap, error = self.thumbnails.get(item)
        has_pixmap = pixmap is not None and not pixmap.isNull()
        if has_pixmap:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if self.crop_mode:
                # Center-crop (Cover) for wall-to-wall gallery grid
                scaled = pixmap.size().scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding)
                target = QRectF(box.center().x() - scaled.width() / 2,
                                box.center().y() - scaled.height() / 2,
                                scaled.width(), scaled.height())
                painter.drawPixmap(target.toRect(), pixmap)
            else:
                # Fit (Contain) without cropping or stretching, with crisp inner rounding
                scaled = pixmap.size().scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
                target = QRectF(box.center().x() - scaled.width() / 2,
                                box.center().y() - scaled.height() / 2,
                                scaled.width(), scaled.height())
                inner_clip = QPainterPath()
                inner_radius = radius if (abs(target.width() - box.width()) <= 2 and abs(target.height() - box.height()) <= 2) else 6.0
                inner_clip.addRoundedRect(target, inner_radius, inner_radius)
                painter.setClipPath(inner_clip)
                painter.drawPixmap(target.toRect(), pixmap)
                painter.setClipPath(clip)
                # Whisper-soft hairline around the photo itself so white skies stay defined
                edge_color = QColor(255, 255, 255, 18) if self.dark else QColor(15, 23, 42, 16)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(edge_color, 1))
                painter.drawRoundedRect(target.adjusted(0.5, 0.5, -0.5, -0.5), inner_radius, inner_radius)

            if hovered:
                overlay = QColor(255, 255, 255, 14) if self.dark else QColor(255, 255, 255, 18)
                painter.fillRect(box, overlay)
        else:
            painter.setPen(QColor(t["muted"]))
            font = QFont("Segoe UI", 9)
            painter.setFont(font)
            text = "无法读取\n打开查看详情" if error else "正在加载…"
            if item.kind == "video":
                text = "无法读取视频\n点击查看详情" if error else "正在提取封面…"
            painter.drawText(box.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignCenter, text)

        painter.setClipping(False)

        # Refined video play badge & compact duration pill
        if item.kind == "video":
            if has_pixmap:
                diameter = max(30.0, min(44.0, box.width() * 0.24))
                center = box.center()
                badge_bg = QColor(t["accent"]) if hovered else QColor(12, 16, 24, 155)
                if hovered:
                    badge_bg.setAlpha(220)
                painter.setBrush(badge_bg)
                painter.setPen(QPen(QColor(255, 255, 255, 165 if hovered else 120), 1.2))
                painter.drawEllipse(center, diameter / 2, diameter / 2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#ffffff"))
                painter.drawPolygon(QPolygonF([
                    QPointF(center.x() - diameter * 0.12, center.y() - diameter * 0.19),
                    QPointF(center.x() - diameter * 0.12, center.y() + diameter * 0.19),
                    QPointF(center.x() + diameter * 0.22, center.y()),
                ]))
            duration = self.thumbnails.duration(item)
            if duration:
                dur_text = format_duration(duration)
                dur_font = QFont("Segoe UI", 8)
                dur_font.setWeight(QFont.Weight.Medium)
                painter.setFont(dur_font)
                fm = painter.fontMetrics()
                pill_w = max(38.0, fm.horizontalAdvance(dur_text) + 12.0)
                pill_h = 20.0
                duration_box = QRectF(box.right() - pill_w - 7, box.bottom() - pill_h - 7, pill_w, pill_h)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(12, 15, 22, 185))
                painter.drawRoundedRect(duration_box, 6, 6)
                painter.setPen(QColor("#f8fafc"))
                painter.drawText(duration_box, Qt.AlignmentFlag.AlignCenter, dur_text)

        # Crisp outer border for selected / hovered / subtle resting frame
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t["accent"]), 2))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        elif hovered:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t["border_strong"]), 1))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        elif not self.crop_mode:
            frame_border = QColor(t["border"])
            frame_border.setAlpha(120)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(frame_border, 1))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        # Minimal date caption underneath
        caption_font = QFont("Segoe UI", 8)
        caption_font.setWeight(QFont.Weight.Medium if selected else QFont.Weight.Normal)
        painter.setFont(caption_font)
        painter.setPen(QColor(t["accent"] if selected else (t["text_secondary"] if hovered else t["muted"])))
        date_box = QRectF(option.rect.x() + 7, box.bottom() + 4, self.edge, 20)
        date_text = item.taken_at.strftime("%Y.%m.%d  %H:%M") if item.taken_at else "未识别日期"
        elided_date = painter.fontMetrics().elidedText(date_text, Qt.TextElideMode.ElideRight, int(date_box.width()))
        painter.drawText(date_box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, elided_date)
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

    def set_crop_mode(self, crop: bool):
        self.delegate.crop_mode = crop
        self.viewport().update()

    def set_thumbnail_size(self, edge: int):
        self.requested_edge = edge
        self.fit_columns()

    def fit_columns(self):
        self.reflow_timer.start()

    def _fit_columns(self):
        width = grid_layout_width(self)
        columns = max(1, round(width / (self.requested_edge + 14)))
        edge = max(64, width // columns - 14)
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
