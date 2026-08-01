from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath

def parse_hex_color(hex_str: str, alpha: int = 220) -> QColor:
    try:
        hex_str = hex_str.strip().lstrip('#')
        if len(hex_str) == 6:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            return QColor(r, g, b, alpha)
    except Exception:
        pass
    return QColor(255, 0, 0, alpha)

class ScreenOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        screen_rect = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_rect)
        self.shapes = []

    def add_shape(self, shape_type, data):
        self.shapes.append({'type': shape_type, 'data': data})
        self.update()
        QApplication.processEvents()  # 強制單執行緒立刻渲染畫面

    def clear(self):
        self.shapes.clear()
        self.update()
        QApplication.processEvents()

    def erase_near(self, x: int, y: int, radius: int = 40):
        """局部橡皮擦：清除指定點 (x, y) 半徑內的筆跡/圖形"""
        r_sq = radius ** 2
        new_shapes = []
        for item in self.shapes:
            stype = item['type']
            data = item['data']
            keep = True

            if stype == 'box':
                cx, cy = data['x'], data['y']
                if (cx - x) ** 2 + (cy - y) ** 2 <= r_sq:
                    keep = False
            elif stype == 'line':
                cx, cy = data['x1'], data['y1']
                if (cx - x) ** 2 + (cy - y) ** 2 <= r_sq:
                    keep = False
            elif stype == 'stroke':
                for px, py in data.get('points', []):
                    if (px - x) ** 2 + (py - y) ** 2 <= r_sq:
                        keep = False
                        break

            if keep:
                new_shapes.append(item)

        self.shapes = new_shapes
        self.update()
        QApplication.processEvents()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 取得 DPI 縮放倍率 (例如 1.25)
        dpr = self.devicePixelRatio()

        for item in self.shapes:
            stype = item['type']
            data = item['data']
            color_hex = data.get('color', '#FF0000')

            main_color = parse_hex_color(color_hex, 220)
            bg_color = parse_hex_color(color_hex, 30)

            if stype == 'box':
                pen = QPen(main_color, 3)
                painter.setPen(pen)
                painter.setBrush(QBrush(bg_color))

                # 物理座標除以 dpr 轉換為邏輯座標
                x = int(data['x'] / dpr)
                y = int(data['y'] / dpr)
                w = int(data['w'] / dpr)
                h = int(data['h'] / dpr)

                painter.drawRect(x, y, w, h)

                if 'label' in data and data['label']:
                    painter.setPen(QPen(QColor(255, 255, 255)))
                    painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                    painter.fillRect(x, y - 20, len(data['label']) * 10, 20, main_color)
                    painter.drawText(x + 5, y - 5, data['label'])

            elif stype == 'line':
                pen = QPen(main_color, 4)
                painter.setPen(pen)

                x1 = int(data['x1'] / dpr)
                y1 = int(data['y1'] / dpr)
                x2 = int(data['x2'] / dpr)
                y2 = int(data['y2'] / dpr)

                painter.drawLine(x1, y1, x2, y2)

            elif stype == 'stroke':
                pen_width = data.get('width', 3)
                pen = QPen(main_color, pen_width)
                painter.setPen(pen)

                points = data.get('points', [])
                if len(points) > 1:
                    path = QPainterPath()
                    path.moveTo(int(points[0][0] / dpr), int(points[0][1] / dpr))
                    for pt in points[1:]:
                        path.lineTo(int(pt[0] / dpr), int(pt[1] / dpr))
                    painter.drawPath(path)

class OverlayBridge(QObject):
    add_shape_signal = pyqtSignal(str, dict)
    clear_signal = pyqtSignal()
    erase_signal = pyqtSignal(int, int, int)

class OverlayManager:
    def __init__(self, overlay: ScreenOverlay):
        self.overlay = overlay
        self.bridge = OverlayBridge()
        self.bridge.add_shape_signal.connect(self.overlay.add_shape)
        self.bridge.clear_signal.connect(self.overlay.clear)
        self.bridge.erase_signal.connect(self.overlay.erase_near)

    def draw_box(self, x: int, y: int, width: int, height: int, label: str = "", color: str = "#FF0000") -> str:
        self.bridge.add_shape_signal.emit('box', {'x': x, 'y': y, 'w': width, 'h': height, 'label': label, 'color': color})
        return f"Drew box at ({x}, {y}, {width}, {height}) with color {color} and label '{label}'"

    def draw_line(self, x1: int, y1: int, x2: int, y2: int, color: str = "#FFFF00") -> str:
        self.bridge.add_shape_signal.emit('line', {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'color': color})
        return f"Drew line from ({x1}, {y1}) to ({x2}, {y2}) with color {color}"

    def draw_stroke(self, points: list, color: str = "#00FF00", width: int = 3) -> str:
        """讓 LLM 畫連續塗鴉/畫筆筆畫，points 格式為 [[x1, y1], [x2, y2], ...]"""
        self.bridge.add_shape_signal.emit('stroke', {'points': points, 'color': color, 'width': width})
        return f"Drew stroke with {len(points)} points"

    def erase_at(self, x: int, y: int, radius: int = 40) -> str:
        """橡皮擦：擦除特定座標附近的筆畫"""
        self.bridge.erase_signal.emit(x, y, radius)
        return f"Erased drawings near ({x}, {y}) within radius {radius}"

    def clear_drawings(self) -> str:
        self.bridge.clear_signal.emit()
        return "Cleared all screen drawings"