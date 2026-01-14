from PySide6.QtWidgets import QWidget, QMenu
from PySide6.QtCore import Qt, QPoint, QRect, Signal, QSize
from PySide6.QtGui import QPainter, QPen, QColor, QImage, QPixmap, QCursor, QAction

class LabelingCanvas(QWidget):
    """
    数据标注专用的画布控件
    支持：画框、选中、删除、缩放预览
    """
    box_added = Signal(list)  # 当新框画完时发射 [x, y, w, h] (像素坐标)
    box_selected = Signal(int) # 当选中某个框时发射索引
    box_deleted = Signal(int)  # 当删除某个框时发射索引
    box_edit_requested = Signal(int) # 当请求编辑某个框的标签时发射索引

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.image = QImage()
        self.pixmap = QPixmap()
        self.img_rect = QRect() # 初始化图片显示区域
        
        self.boxes = []         # 存储当前图片的框 [[x, y, w, h, class_id], ...]
        self.selected_idx = -1
        
        # 交互状态
        self.drawing = False
        self.resizing = False
        self.moving = False     # 是否正在移动框
        self.draw_mode = False  # 是否处于标注模式（按下 W 开启）
        self.resize_edge = None # 'top', 'bottom', 'left', 'right', 'top-left', etc.
        self.start_pos = QPoint()
        self.current_pos = QPoint()
        self.orig_box = None    # 记录缩放开始时的原始框坐标
        
        # 样式设置
        self.line_color = QColor(0, 120, 212) # 蓝色
        self.select_color = QColor(255, 255, 255) # 选中时显示为白色，以便区分
        self.handle_size = 8 # 缩放手柄大小
        
        # 预定义颜色序列
        self.colors = [
            QColor(255, 0, 0),      # 红色
            QColor(0, 255, 0),      # 绿色
            QColor(0, 0, 255),      # 蓝色
            QColor(255, 255, 0),    # 黄色
            QColor(255, 0, 255),    # 紫红色
            QColor(0, 255, 255),    # 青色
            QColor(255, 165, 0),    # 橙色
            QColor(128, 0, 128),    # 紫色
            QColor(0, 128, 128),    # 深青色
            QColor(128, 128, 0),    # 橄榄色
        ]
        
        self.setCursor(QCursor(Qt.ArrowCursor))
        self.classes = [] # 存储标签名称，用于稳定颜色分配

    def set_classes(self, classes):
        """设置标签名称列表"""
        self.classes = classes

    def get_color(self, class_id):
        """根据标签名称获取颜色，确保删除其他标签时颜色保持稳定"""
        if 0 <= class_id < len(self.classes):
            name = self.classes[class_id]
            # 简单的确定性哈希：根据名称字符串计算一个固定的索引
            h = sum(ord(c) * (i + 1) for i, c in enumerate(name))
            return self.colors[h % len(self.colors)]
        # 如果找不到名称，回退到 ID 分配
        return self.colors[class_id % len(self.colors)]

    def set_image(self, image_path):
        """加载并显示图片"""
        self.pixmap = QPixmap(image_path)
        self.boxes = []
        self.selected_idx = -1
        self.update()

    def set_boxes(self, boxes):
        """设置已有的框"""
        self.boxes = boxes
        self.update()

    def paintEvent(self, event):
        if self.pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1. 绘制图片（居中并保持比例）
        scaled_pixmap = self.pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.img_rect = scaled_pixmap.rect()
        self.img_rect.moveCenter(self.rect().center())
        painter.drawPixmap(self.img_rect, scaled_pixmap)

        # 2. 绘制已有的框
        for i, box in enumerate(self.boxes):
            rect = self._map_to_widget(box[:4])
            is_selected = (i == self.selected_idx)
            
            class_id = box[4] if len(box) > 4 else 0
            color = self.get_color(class_id)
            
            # 绘制框
            painter.setPen(QPen(color, 2))
            if is_selected:
                painter.setPen(QPen(self.select_color, 2, Qt.DashLine))
            painter.drawRect(rect)
            
            # 绘制 class_id 标签背景
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            label_rect = QRect(rect.x(), rect.y() - 20, 30, 20)
            painter.drawRect(label_rect)
            
            # 绘制文本
            painter.setPen(Qt.white if color.lightness() < 150 else Qt.black)
            painter.drawText(label_rect, Qt.AlignCenter, str(class_id))
            painter.setBrush(Qt.NoBrush)

            # 如果选中，绘制缩放手柄
            if is_selected:
                painter.setBrush(Qt.white)
                painter.setPen(QPen(self.select_color, 1))
                handles = self._get_handles(rect)
                for h in handles.values():
                    painter.drawRect(h)
                painter.setBrush(Qt.NoBrush)

        # 3. 绘制正在画的框
        if self.drawing:
            painter.setPen(QPen(self.line_color, 2, Qt.DashLine))
            temp_rect = QRect(self.start_pos, self.current_pos).normalized()
            painter.drawRect(temp_rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            if not self.img_rect.contains(pos):
                return
            
            # 1. 检查是否点击了选中框的缩放手柄
            if self.selected_idx >= 0:
                rect = self._map_to_widget(self.boxes[self.selected_idx][:4])
                handles = self._get_handles(rect)
                for edge, h_rect in handles.items():
                    if h_rect.contains(pos):
                        self.resizing = True
                        self.resize_edge = edge
                        self.start_pos = pos
                        self.orig_box = list(self.boxes[self.selected_idx])
                        return

            # 2. 检查是否点击了已有的框（准备移动或选中）
            found = False
            for i, box in enumerate(self.boxes):
                rect = self._map_to_widget(box[:4])
                if rect.contains(pos):
                    self.selected_idx = i
                    self.box_selected.emit(i)
                    self.moving = True # 开启移动模式
                    self.start_pos = pos
                    self.orig_box = list(self.boxes[i])
                    found = True
                    break
            
            # 3. 如果没点到框，且处于标注模式，开始画新框
            if not found and self.draw_mode:
                self.drawing = True
                self.start_pos = pos
                self.current_pos = pos
                self.selected_idx = -1
            elif not found:
                self.selected_idx = -1
            
            self.update()

    def contextMenuEvent(self, event):
        pos = event.pos()
        # 检查是否点在某个框上
        hit_idx = -1
        for i, box in enumerate(self.boxes):
            rect = self._map_to_widget(box[:4])
            if rect.contains(pos):
                hit_idx = i
                break
        
        if hit_idx >= 0:
            self.selected_idx = hit_idx
            self.box_selected.emit(hit_idx)
            self.update()
            
            menu = QMenu(self)
            delete_action = QAction("删除框 (Delete)", self)
            delete_action.triggered.connect(lambda: self.box_deleted.emit(hit_idx))
            edit_action = QAction("修改标签", self)
            edit_action.triggered.connect(lambda: self.box_edit_requested.emit(hit_idx))
            
            menu.addAction(edit_action)
            menu.addAction(delete_action)
            menu.exec_(event.globalPos())

    def mouseDoubleClickEvent(self, event):
        """双击请求修改标签"""
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            for i, box in enumerate(self.boxes):
                rect = self._map_to_widget(box[:4])
                if rect.contains(pos):
                    self.selected_idx = i
                    self.box_selected.emit(i)
                    self.box_edit_requested.emit(i)
                    self.update()
                    break

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self.pixmap.isNull():
            return
            
        # 处理缩放逻辑
        if self.resizing and self.selected_idx >= 0 and self.orig_box:
            orig_rect = self._map_to_widget(self.orig_box[:4])
            diff = pos - self.start_pos
            new_rect = QRect(orig_rect)
            if 'left' in self.resize_edge:
                new_rect.setLeft(orig_rect.left() + diff.x())
            if 'right' in self.resize_edge:
                new_rect.setRight(orig_rect.right() + diff.x())
            if 'top' in self.resize_edge:
                new_rect.setTop(orig_rect.top() + diff.y())
            if 'bottom' in self.resize_edge:
                new_rect.setBottom(orig_rect.bottom() + diff.y())
            
            new_rect = new_rect.intersected(self.img_rect)
            if new_rect.width() > 5 and new_rect.height() > 5:
                pixel_box = self._map_to_pixel(new_rect)
                if len(self.boxes[self.selected_idx]) > 4:
                    self.boxes[self.selected_idx] = pixel_box + [self.boxes[self.selected_idx][4]]
                else:
                    self.boxes[self.selected_idx] = pixel_box + [0]
                self.update()
            return

        # 处理移动逻辑
        if self.moving and self.selected_idx >= 0 and self.orig_box:
            diff = pos - self.start_pos
            orig_rect = self._map_to_widget(self.orig_box[:4])
            new_rect = QRect(orig_rect)
            new_rect.translate(diff)
            
            # 限制在图片范围内
            if new_rect.left() < self.img_rect.left(): new_rect.moveLeft(self.img_rect.left())
            if new_rect.right() > self.img_rect.right(): new_rect.moveRight(self.img_rect.right())
            if new_rect.top() < self.img_rect.top(): new_rect.moveTop(self.img_rect.top())
            if new_rect.bottom() > self.img_rect.bottom(): new_rect.moveBottom(self.img_rect.bottom())
            
            pixel_box = self._map_to_pixel(new_rect)
            if len(self.boxes[self.selected_idx]) > 4:
                self.boxes[self.selected_idx] = pixel_box + [self.boxes[self.selected_idx][4]]
            else:
                self.boxes[self.selected_idx] = pixel_box + [0]
            self.update()
            return

        # 处理画框逻辑
        if self.drawing:
            self.current_pos = pos
            self.update()
            return

        # 更新鼠标样式
        if self.img_rect.contains(pos):
            # 1. 检查是否在手柄上
            if self.selected_idx >= 0:
                rect = self._map_to_widget(self.boxes[self.selected_idx][:4])
                handles = self._get_handles(rect)
                for edge, h_rect in handles.items():
                    if h_rect.contains(pos):
                        if edge in ['top', 'bottom']: self.setCursor(Qt.SizeVerCursor)
                        elif edge in ['left', 'right']: self.setCursor(Qt.SizeHorCursor)
                        elif edge in ['top-left', 'bottom-right']: self.setCursor(Qt.SizeFDiagCursor)
                        else: self.setCursor(Qt.SizeBDiagCursor)
                        return
            
            # 2. 检查是否在某个框内
            in_box = False
            for i, box in enumerate(self.boxes):
                rect = self._map_to_widget(box[:4])
                if rect.contains(pos):
                    in_box = True
                    break
            
            if in_box:
                # 如果是选中的框，显示移动图标
                if i == self.selected_idx:
                    self.setCursor(Qt.SizeAllCursor)
                else:
                    self.setCursor(Qt.PointingHandCursor)
            elif self.draw_mode:
                self.setCursor(Qt.CrossCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.resizing or self.moving:
                # 只有当位置确实发生变化时才触发保存
                if self.orig_box and self.selected_idx >= 0:
                    current_box = self.boxes[self.selected_idx][:4]
                    if current_box != self.orig_box[:4]:
                        self.box_added.emit(None) # 触发保存
                
                self.resizing = False
                self.moving = False
                self.resize_edge = None
                self.orig_box = None
            elif self.drawing:
                self.drawing = False
                end_pos = event.pos()
                rect = QRect(self.start_pos, end_pos).normalized()
                if rect.width() > 5 and rect.height() > 5:
                    pixel_box = self._map_to_pixel(rect)
                    self.box_added.emit(pixel_box)
            
            self.update()

    def _get_handles(self, rect):
        """获取 8 个方向的缩放手柄矩形"""
        s = self.handle_size
        s2 = s // 2
        return {
            'top-left': QRect(rect.left() - s2, rect.top() - s2, s, s),
            'top': QRect(rect.center().x() - s2, rect.top() - s2, s, s),
            'top-right': QRect(rect.right() - s2, rect.top() - s2, s, s),
            'right': QRect(rect.right() - s2, rect.center().y() - s2, s, s),
            'bottom-right': QRect(rect.right() - s2, rect.bottom() - s2, s, s),
            'bottom': QRect(rect.center().x() - s2, rect.bottom() - s2, s, s),
            'bottom-left': QRect(rect.left() - s2, rect.bottom() - s2, s, s),
            'left': QRect(rect.left() - s2, rect.center().y() - s2, s, s),
        }

    def _map_to_widget(self, pixel_box):
        """将像素坐标映射到控件显示坐标"""
        if len(pixel_box) < 4:
            return QRect()
        px, py, pw, ph = pixel_box[:4]
        ratio = self.img_rect.width() / self.pixmap.width()
        wx = self.img_rect.x() + px * ratio
        wy = self.img_rect.y() + py * ratio
        ww = pw * ratio
        wh = ph * ratio
        return QRect(int(wx), int(wy), int(ww), int(wh))

    def _map_to_pixel(self, widget_rect):
        """将控件显示坐标映射回原始像素坐标"""
        ratio = self.pixmap.width() / self.img_rect.width()
        px = (widget_rect.x() - self.img_rect.x()) * ratio
        py = (widget_rect.y() - self.img_rect.y()) * ratio
        pw = widget_rect.width() * ratio
        ph = widget_rect.height() * ratio
        return [int(px), int(py), int(pw), int(ph)]
