from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from .model import HANDLES, SIDES

HANDLE_HIT = 7
PADDING_HANDLES = {"n", "e", "s", "w"}
CURSORS = {
    "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
    "w": Qt.CursorShape.SizeHorCursor, "e": Qt.CursorShape.SizeHorCursor,
}
ARROWS = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
          Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}


class MirrorPreview(QGraphicsView):
    selected = Signal(str)
    edited = Signal(str, str, object, int, int)
    nudged = Signal(int, int)

    def __init__(self, layout, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setAccessibleName("Interactive mirror preview")
        self.set_padding_mode(False)
        self.setMinimumSize(260, 210)
        self.layout_model = None
        self.side = "left"
        self.image = QImage()
        self.gesture = None
        self.set_layout(layout, self.side)

    def set_layout(self, layout, side):
        dimensions = (layout.width, layout.height)
        needs_fit = self.layout_model is None or dimensions != (
            self.layout_model.width, self.layout_model.height)
        self.layout_model = layout
        self.side = side
        if needs_fit:
            self.scene().setSceneRect(QRectF(0, 0, *dimensions))
            self.fit_screen()
        self.viewport().update()

    def fit_screen(self):
        area = self.viewport().rect().adjusted(19, 19, -19, -19)
        screen = self.sceneRect()
        if area.isEmpty() or screen.isEmpty():
            return
        scale = min(area.width() / screen.width(), area.height() / screen.height())
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(screen.center())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_screen()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_screen()

    def set_image(self, image):
        self.image = image
        self.viewport().update()

    def set_padding_mode(self, enabled):
        self.padding_mode = enabled
        if enabled:
            self.setToolTip("Drag an amber frame handle to adjust padding on all sides.")
        else:
            self.setToolTip("Select and drag a mirror. Use its handles to resize, "
                            "or use Arrow and Shift+Arrow to move it.")
        self.viewport().update()

    def drawBackground(self, painter, rect):
        screen = self.sceneRect()
        painter.fillRect(rect, QColor("#101820"))
        painter.fillRect(screen, QColor("#263642"))
        if not self.image.isNull():
            scale = min(screen.width() / self.image.width(), screen.height() / self.image.height())
            target = QRectF(0, 0, self.image.width() * scale, self.image.height() * scale)
            target.moveCenter(screen.center())
            painter.drawImage(target, self.image)
        else:
            pen = QPen(QColor("#344957"))
            pen.setCosmetic(True)
            painter.setPen(pen)
            for i in range(1, 8):
                x, y = screen.width() * i / 8, screen.height() * i / 8
                painter.drawLine(QPointF(x, 0), QPointF(x, screen.height()))
                painter.drawLine(QPointF(0, y), QPointF(screen.width(), y))
        pen = QPen(QColor("#708692"))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(screen)

    def _rect(self, side):
        mirror = self.layout_model.mirror(side)
        return QRectF(mirror.x, mirror.y, mirror.width, mirror.height)

    def _frame_rect(self, side):
        layout = self.layout_model
        x0, y0, x1, y1 = layout.mirror(side).frame(layout.width, layout.height)
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def handles(self):
        box = self._frame_rect(self.side) if self.padding_mode else self._rect(self.side)
        return {
            name: self.mapFromScene(QPointF(box.center().x() + h * box.width() / 2,
                                           box.center().y() + v * box.height() / 2))
            for name, (h, v) in HANDLES.items()
            if not self.padding_mode or name in PADDING_HANDLES
        }

    def drawForeground(self, painter, _rect):
        other = "right" if self.side == "left" else "left"
        amber = QColor("#FFD183")
        for side in (other, self.side):
            selected = side == self.side
            color = QColor("#72E4D4" if selected else "#B1CBDA")
            frame = self._frame_rect(side)
            painter.fillRect(frame, QColor(10, 20, 28, 175))
            box = self._rect(side)
            painter.fillRect(box, QColor(40, 108, 109, 120) if selected
                             else QColor(39, 65, 84, 135))
            pen = QPen(color, 2 if selected else 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(box)
            if selected and self.padding_mode:
                pen = QPen(amber, 2, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawRect(frame)
                painter.setPen(color)
            elif frame != box:
                pen = QPen(QColor("#82949E" if selected else "#526572"))
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawRect(frame)
                painter.setPen(color)
            painter.save()
            painter.resetTransform()
            center = self.mapFromScene(box.center())
            view_width = box.width() * self.transform().m11()
            view_height = box.height() * self.transform().m22()
            if view_width >= 36 and view_height >= 21:
                label = side.upper()
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(QRectF(center.x() - view_width / 2, center.y() - 10,
                                        view_width, 20), Qt.AlignmentFlag.AlignCenter, label)
            painter.restore()

        painter.save()
        painter.resetTransform()
        painter.setPen(QPen(QColor("#182831")))
        painter.setBrush(amber if self.padding_mode else QColor("#9AF9E9"))
        for point in self.handles().values():
            painter.drawRect(QRectF(point.x() - 3.5, point.y() - 3.5, 7, 7))
        painter.restore()

    def _handle_at(self, point):
        handles = self.handles()
        nearest = min(handles, key=lambda name: (point - handles[name]).manhattanLength())
        distance = point - handles[nearest]
        return nearest if max(abs(distance.x()), abs(distance.y())) <= HANDLE_HIT else None

    def _side_at(self, point):
        position = self.mapToScene(point)
        return next((side for side in (self.side, *SIDES) if self._rect(side).contains(position)),
                    None)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        point = event.position().toPoint()
        handle = self._handle_at(point)
        side = self.side if handle else self._side_at(point)
        if side is not None:
            self.selected.emit(side)
            if handle and self.padding_mode:
                handle = f"padding:{handle}"
            self.gesture = (self.mapToScene(point), side, handle or "move",
                            self.layout_model.mirror(side))
            event.accept()
        else:
            super().mousePressEvent(event)

    def _update_gesture(self, point: QPoint):
        start, side, handle, mirror = self.gesture
        delta = self.mapToScene(point) - start
        self.edited.emit(side, handle, mirror, round(delta.x()), round(delta.y()))

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        if self.gesture:
            self._update_gesture(point)
            event.accept()
            return
        handle = self._handle_at(point)
        cursor = CURSORS[handle] if handle else (
            Qt.CursorShape.OpenHandCursor if self._side_at(point) else Qt.CursorShape.ArrowCursor)
        self.viewport().setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.gesture and event.button() == Qt.MouseButton.LeftButton:
            self._update_gesture(event.position().toPoint())
            self.gesture = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in ARROWS:
            x, y = ARROWS[event.key()]
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.nudged.emit(x * step, y * step)
            event.accept()
        else:
            super().keyPressEvent(event)
