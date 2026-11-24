"""Match QListView's wrapping bounds, including its reserved scrollbar gutter."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListView, QStyle, QStyleOption


def grid_layout_width(view: QListView) -> int:
    # Qt's prepareItemsLayout reserves the scrollbar even while it is hidden.
    # Using viewport().width() alone can make the last cell exceed those bounds
    # by only a few pixels, forcing a whole column onto the next row.
    width = view.maximumViewportSize().width()
    bar = view.verticalScrollBar()
    style = view.style()
    if (view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
            and (view.flow() == QListView.Flow.LeftToRight or bar.isVisible())
            and not style.pixelMetric(QStyle.PixelMetric.PM_ScrollView_ScrollBarOverlap, None, bar)):
        margin = style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, bar)
        if style.styleHint(QStyle.StyleHint.SH_ScrollView_FrameOnlyAroundContents, None, view):
            option = QStyleOption()
            option.initFrom(view)
            margin += 2 * style.pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth, option, view)
        width -= margin
    # IconMode compares the next cell's exclusive right edge to QRect.right(),
    # which is inclusive. Leave that last pixel unused even at exact division.
    return max(1, width - 1)
