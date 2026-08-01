from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont

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
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        screen_rect = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_rect)
        self.shapes = []

    def add_shape(self, shape_type, data):
        self.shapes.append({'type': shape_type, 'data': data})
        self.update()

    def clear(self):
        self.shapes.clear()
        self.update()

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

class OverlayBridge(QObject):
    add_shape_signal = pyqtSignal(str, dict)
    clear_signal = pyqtSignal()

class OverlayManager:
    def __init__(self, overlay: ScreenOverlay):
        self.overlay = overlay
        self.bridge = OverlayBridge()
        self.bridge.add_shape_signal.connect(self.overlay.add_shape)
        self.bridge.clear_signal.connect(self.overlay.clear)

    def draw_box(self, x: int, y: int, width: int, height: int, label: str = "", color: str = "#FF0000") -> str:
        self.bridge.add_shape_signal.emit('box', {'x': x, 'y': y, 'w': width, 'h': height, 'label': label, 'color': color})
        return f"Drew box at ({x}, {y}, {width}, {height}) with color {color} and label '{label}'"

    def draw_line(self, x1: int, y1: int, x2: int, y2: int, color: str = "#FFFF00") -> str:
        self.bridge.add_shape_signal.emit('line', {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'color': color})
        return f"Drew line from ({x1}, {y1}) to ({x2}, {y2}) with color {color}"

    def clear_drawings(self) -> str:
        self.bridge.clear_signal.emit()
        return "Cleared all screen drawings"