from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
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

def _point_segment_dist_sq(px, py, ax, ay, bx, by):
    """點 (px, py) 到線段 (ax, ay)-(bx, by) 的最短距離平方。
    erase_near 對 stroke 要判斷的是「使用者點的位置有沒有碰到這條畫出來的曲線」，
    曲線是點與點之間連起來的線段，不是只有存下來的那幾個頂點本身。
    """
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2

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

        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        else:
            self.setGeometry(0, 0, 1920, 1080)
        self.shapes = []

    def add_shape(self, shape_type, data):
        self.shapes.append({'type': shape_type, 'data': data})
        self.update()
        QApplication.processEvents()  # 強制單執行緒立刻渲染畫面

    def add_mouse_trajectory(self, from_xy, to_xy, duration_ms=400, color="#00BFFF"):
        """畫一條從 from_xy 到 to_xy 的軌跡線，並用計時器讓一個圓點沿著這條線
        移動，模擬滑鼠實際會怎麼移過去，而不是憑空瞬移——這是「瞬間輸入」
        開關關閉時，agent 真的移動滑鼠之前用來讓使用者先看到「將會移到哪」
        的預覽，不是最終真正的滑鼠移動本身（那還是由 pyautogui 執行）。

        線本身立刻整條畫出來（讓使用者馬上看到終點在哪），圓點才是真正
        沿著時間軸移動的部分，兩者疊在一起看起來就像「一個游標沿著這條線
        滑過去」。
        """
        line_shape = {'type': 'line', 'data': {
            'x1': from_xy[0], 'y1': from_xy[1],
            'x2': to_xy[0], 'y2': to_xy[1], 'color': color,
        }}
        dot_shape = {'type': 'stroke', 'data': {
            'points': [[from_xy[0], from_xy[1]]], 'color': color, 'width': 10,
        }}
        self.shapes.append(line_shape)
        self.shapes.append(dot_shape)
        self.update()
        QApplication.processEvents()

        steps = max(1, duration_ms // 16)  # 大約 60fps
        state = {"i": 0}
        timer = QTimer(self)

        def _advance():
            state["i"] += 1
            t = min(1.0, state["i"] / steps)
            x = from_xy[0] + (to_xy[0] - from_xy[0]) * t
            y = from_xy[1] + (to_xy[1] - from_xy[1]) * t
            dot_shape['data']['points'] = [[x, y]]
            self.update()
            QApplication.processEvents()
            if t >= 1.0:
                timer.stop()

        timer.timeout.connect(_advance)
        timer.start(16)

    def add_typing_preview(self, x, y, text, char_interval_ms=30):
        """在 (x, y) 上方顯示一個文字泡泡，用計時器逐字顯示 text，製造打字
        動畫的效果——這是「瞬間輸入」開關關閉時，agent 真的打字之前用來
        讓使用者先看到「將會打什麼字」的預覽，不是最終真正的鍵盤輸入本身
        （那還是由 pyautogui 執行）。

        char_interval_ms 是每個字元之間的間隔，跟 type_text() 本身的
        interval 參數是兩回事——這裡純粹是視覺呈現的節奏，不影響真正打字
        的速度。字數多的時候會自動全部播完才停止計時器，不會卡在中間。
        """
        shape = {'type': 'typing_preview', 'data': {
            'x': x, 'y': y, 'full_text': text, 'revealed': 0,
        }}
        self.shapes.append(shape)
        self.update()
        QApplication.processEvents()

        timer = QTimer(self)

        def _reveal_next():
            if shape['data']['revealed'] < len(text):
                shape['data']['revealed'] += 1
                self.update()
                QApplication.processEvents()
            else:
                timer.stop()

        timer.timeout.connect(_reveal_next)
        timer.start(max(10, char_interval_ms))

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
                pts = data.get('points', [])
                if len(pts) == 1:
                    px, py = pts[0]
                    if (px - x) ** 2 + (py - y) ** 2 <= r_sq:
                        keep = False
                else:
                    for i in range(len(pts) - 1):
                        ax, ay = pts[i]
                        bx, by = pts[i + 1]
                        if _point_segment_dist_sq(x, y, ax, ay, bx, by) <= r_sq:
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
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)

                points = data.get('points', [])
                if len(points) == 1:
                    # 只有一個點：畫一個實心圓點當標記，而不是靜默地什麼都不畫
                    cx = int(points[0][0] / dpr)
                    cy = int(points[0][1] / dpr)
                    r = max(pen_width, 3)
                    painter.setBrush(QBrush(main_color))
                    painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
                elif len(points) > 1:
                    path = QPainterPath()
                    path.moveTo(int(points[0][0] / dpr), int(points[0][1] / dpr))
                    for pt in points[1:]:
                        path.lineTo(int(pt[0] / dpr), int(pt[1] / dpr))
                    painter.drawPath(path)

            elif stype == 'typing_preview':
                # 顯示「即將輸入的文字」的預覽泡泡：revealed 由計時器逐次遞增，
                # 只畫出 full_text 裡前 revealed 個字元，製造打字動畫的效果。
                x = int(data['x'] / dpr)
                y = int(data['y'] / dpr)
                full_text = data.get('full_text', '')
                revealed = data.get('revealed', len(full_text))
                shown = full_text[:revealed]
                cursor = "▏" if revealed < len(full_text) else ""

                painter.setFont(QFont("Consolas", 11))
                metrics = painter.fontMetrics()
                # 寬度用完整文字量測，不要隨著 revealed 增加而讓泡泡一直變寬跳動
                text_w = metrics.horizontalAdvance(full_text) + 16
                text_h = metrics.height() + 12

                bubble_y = y - text_h - 10
                painter.setPen(QPen(main_color, 2))
                painter.setBrush(QBrush(QColor(20, 20, 20, 235)))
                painter.drawRoundedRect(x, bubble_y, text_w, text_h, 6, 6)

                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(x + 8, bubble_y + text_h - 10, shown + cursor)

class OverlayBridge(QObject):
    add_shape_signal = pyqtSignal(str, dict)
    clear_signal = pyqtSignal()
    erase_signal = pyqtSignal(int, int, int)
    trajectory_signal = pyqtSignal(list, list, int, str)
    typing_preview_signal = pyqtSignal(int, int, str, int)

class OverlayManager:
    def __init__(self, overlay: ScreenOverlay):
        self.overlay = overlay
        self.bridge = OverlayBridge()
        self.bridge.add_shape_signal.connect(self.overlay.add_shape)
        self.bridge.clear_signal.connect(self.overlay.clear)
        self.bridge.erase_signal.connect(self.overlay.erase_near)
        self.bridge.trajectory_signal.connect(self.overlay.add_mouse_trajectory)
        self.bridge.typing_preview_signal.connect(self.overlay.add_typing_preview)

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

    def show_mouse_trajectory(self, from_xy, to_xy, duration_ms: int = 400, color: str = "#00BFFF") -> str:
        """給「瞬間輸入」關閉時的滑鼠預覽用，不是給 LLM 當一般繪圖工具呼叫——
        沒有寫進 SYSTEM_PROMPT 的工具清單，是 agent_tool_execution.py 的
        物理輸入預覽邏輯內部呼叫的。
        """
        self.bridge.trajectory_signal.emit(list(from_xy), list(to_xy), duration_ms, color)
        return f"Showing mouse trajectory from {tuple(from_xy)} to {tuple(to_xy)}"

    def show_typing_preview(self, x: int, y: int, text: str, char_interval_ms: int = 30) -> str:
        """同上，給打字預覽用，不是一般繪圖工具。"""
        self.bridge.typing_preview_signal.emit(x, y, text, char_interval_ms)
        return f"Showing typing preview for {len(text)} characters at ({x}, {y})"