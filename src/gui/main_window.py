import sys
import os
import shutil
import ctypes
import random
import time
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QPushButton, QLabel, QGroupBox, QDoubleSpinBox, 
                             QCheckBox, QFrame, QSpacerItem, QSizePolicy,
                             QTabWidget, QFileDialog, QProgressBar, QComboBox,
                             QLineEdit, QMessageBox, QSpinBox, QListWidget, QInputDialog, QDialog,
                             QAbstractSpinBox, QTextEdit, QPlainTextEdit, QSplitter, QMenu, QApplication)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QAction, QKeySequence, QShortcut, QPixmap, QPainter, QColor, QImage

class PreviewWindow(QDialog):
    """
    高性能实时预览窗口，使用 PySide6 实现以替代 cv2.imshow。
    支持置顶、不获取焦点、抗锯齿显示。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AutoX 实时预览")
        self.setWindowFlags(
            Qt.Window | 
            Qt.WindowStaysOnTopHint | 
            Qt.WindowDoesNotAcceptFocus |
            Qt.WindowMinMaxButtonsHint
        )
        # 默认不获取焦点，防止游戏掉帧或输入冲突
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("等待图像...")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background-color: black; color: white;")
        layout.addWidget(self.label)
        
        self.resize(640, 480)

    def update_frame(self, frame):
        """兼容旧接口"""
        self.update_frame_with_data(frame, None)

    def update_frame_with_data(self, frame, draw_data):
        """
        更新显示帧并绘制调试信息
        :param frame: BGR 图像 (numpy)
        :param draw_data: 包含 fov_center, results 等信息的字典
        """
        if frame is None:
            return
            
        try:
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            
            # 1. 构造 QImage (零拷贝)
            q_img = QImage(frame.data, width, height, bytes_per_line, QImage.Format_BGR888)
            
            # 2. 转换为 QPixmap 准备绘图
            pixmap = QPixmap.fromImage(q_img)
            
            # 3. 如果有绘制数据，使用 QPainter 在 Pixmap 上绘制
            if draw_data:
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                
                # A. 绘制 FOV
                if 'fov_center' in draw_data and 'fov_radius' in draw_data:
                    cx, cy = draw_data['fov_center']
                    r = draw_data['fov_radius']
                    # QColor(R, G, B)
                    pen = QColor(255, 255, 255) # 白色
                    painter.setPen(pen)
                    painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
                
                # B. 绘制检测结果
                if 'results' in draw_data:
                    target = draw_data.get('target')
                    for (x1, y1, x2, y2, conf, cls) in draw_data['results']:
                        # 默认绿色
                        color = QColor(0, 255, 0)
                        # 如果是目标，红色
                        if target is not None and x1 == target[0] and y1 == target[1]:
                            color = QColor(255, 0, 0)
                        
                        painter.setPen(color)
                        painter.drawRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))

                # C. 绘制 FPS
                if 'fps' in draw_data:
                    fps = draw_data['fps']
                    painter.setPen(QColor(0, 255, 0))
                    # 设置大一点的字体
                    font = painter.font()
                    font.setPointSize(16)
                    font.setBold(True)
                    painter.setFont(font)
                    painter.drawText(20, 40, f"FPS: {fps}")
                
                painter.end()

            # 4. 缩放并显示
            scaled_pixmap = pixmap.scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.label.setPixmap(scaled_pixmap)
            
        except Exception as e:
            print(f"Preview update error: {e}")

from .styles import MAIN_STYLE
from .labeling_canvas import LabelingCanvas
from .overlay_window import OverlayWindow
from utils.config import ConfigManager
from utils.video_processor import VideoProcessor
from utils.yolo_helper import YOLOHelper

from utils.paths import get_abs_path, get_root_path
from utils.hotkey import get_pressed_hotkey_str, is_hotkey_pressed

class HotkeyRecorder(QWidget):
    """
    自定义热键录制组件
    显示当前热键，并提供按钮进行重新录制
    """
    key_changed = Signal(str)

    def __init__(self, current_key="Shift", parent=None):
        super().__init__(parent)
        self.current_key = current_key
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.key_display = QLineEdit(self.current_key)
        self.key_display.setReadOnly(True)
        self.key_display.setPlaceholderText("未设置")
        layout.addWidget(self.key_display)
        
        self.record_btn = QPushButton("配置")
        self.record_btn.setFixedWidth(60)
        self.record_btn.clicked.connect(self._start_recording)
        layout.addWidget(self.record_btn)
        
        self.clear_btn = QPushButton("清除")
        self.clear_btn.setFixedWidth(60)
        self.clear_btn.clicked.connect(self._clear_hotkey)
        layout.addWidget(self.clear_btn)
        
        self.recording = False
        self.recorded_hotkey = None
        self.is_waiting_release = False
        self.last_press_time = 0
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check_keys)

    def set_key(self, key):
        self.current_key = key
        self.key_display.setText(key)

    def get_key(self):
        return self.current_key

    def _clear_hotkey(self):
        """清除当前热键"""
        if self.recording:
            return
        self.current_key = ""
        self.key_display.setText("")
        self.key_changed.emit("")

    def _start_recording(self):
        if self.recording:
            return
            
        self.recording = True
        self.recorded_hotkey = None
        self.is_waiting_release = False
        self.last_press_time = 0
        
        self.record_btn.setText("按键...")
        self.record_btn.setStyleSheet("background-color: #ff9900; color: white;")
        self.key_display.setText("请按下按键 (支持组合键)...")
        self.timer.start(30) # 30ms 轮询一次，提高精度

    def _check_keys(self):
        if not self.recording:
            return
            
        current_hotkey = get_pressed_hotkey_str()
        
        if current_hotkey:
            # 只要有按键按下，就更新记录的最长组合键
            # 比较逻辑：按键数量多优先，按键数量一样时保持现状
            if not self.recorded_hotkey:
                self.recorded_hotkey = current_hotkey
            else:
                current_keys = current_hotkey.split('+')
                recorded_keys = self.recorded_hotkey.split('+')
                if len(current_keys) >= len(recorded_keys):
                    self.recorded_hotkey = current_hotkey
            
            self.last_press_time = time.time()
            self.is_waiting_release = True
            self.key_display.setText(self.recorded_hotkey)
        elif self.is_waiting_release:
            # 如果进入了等待释放状态，且当前没有按键按下
            # 检查是否已经释放了一段时间（例如 300ms），或者距离第一次按键已经很久了
            if time.time() - self.last_press_time > 0.3:
                # 结束录制
                self.recording = False
                self.timer.stop()
                
                if self.recorded_hotkey:
                    self.current_key = self.recorded_hotkey
                    self.key_changed.emit(self.current_key)
                
                self.record_btn.setText("配置")
                self.record_btn.setStyleSheet("")
                self.key_display.setText(self.current_key)
                self.is_waiting_release = False

class TrainingThread(QThread):
    progress = Signal(str)
    epoch_progress = Signal(int, int) # current, total
    finished = Signal(bool, str)

    def __init__(self, model_path, data_yaml, epochs, workers, project_dir, batch=16, cache=False, imgsz=640):
        super().__init__()
        self.model_path = model_path
        self.data_yaml = data_yaml
        self.epochs = epochs
        self.workers = workers
        self.project_dir = project_dir
        self.batch = batch
        self.cache = cache
        self.imgsz = imgsz
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            from ultralytics import YOLO, settings
            from ultralytics.utils import USER_CONFIG_DIR
            import logging
            import re
            import shutil
            
            # 预先处理字体问题，避免训练时自动下载
            try:
                font_name = "Arial.Unicode.ttf"
                target_font_path = USER_CONFIG_DIR / font_name
                if not target_font_path.exists():
                    # 尝试从项目 assets 目录加载
                    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    local_font_path = os.path.join(project_root, "assets", font_name)
                    if os.path.exists(local_font_path):
                        self.progress.emit(f"检测到本地字体，正在安装到配置目录: {target_font_path}")
                        os.makedirs(USER_CONFIG_DIR, exist_ok=True)
                        shutil.copy2(local_font_path, target_font_path)
            except Exception as e:
                print(f"Font localization failed: {e}")

            # ANSI 转义序列正则，用于过滤颜色代码
            ansi_escape = re.compile(r'\x1b\[[0-9;]*[mGKFHD]')
            # 提取 Epoch 进度的正则，例如 "1/200"
            epoch_pattern = re.compile(r'(\d+)/(\d+)')
            
            # 自定义日志处理器，用于捕获训练输出
            class LogHandler(logging.Handler):
                def __init__(self, thread):
                    super().__init__()
                    self.thread = thread
                def emit(self, record):
                    try:
                        msg = self.format(record)
                        # 过滤 ANSI 颜色代码
                        clean_msg = ansi_escape.sub('', msg).replace('\r', '\n')
                        if not clean_msg.strip():
                            return
                        
                        # 确保每条日志都有换行，但避免重复换行
                        self.thread.progress.emit(clean_msg.rstrip() + "\n")
                    except Exception:
                        pass

            # 获取 ultralytics 的日志记录器并添加我们的处理器
            ultralytics_logger = logging.getLogger("ultralytics")
            handler = LogHandler(self)
            handler.setFormatter(logging.Formatter('%(message)s'))
            ultralytics_logger.addHandler(handler)
            ultralytics_logger.setLevel(logging.INFO)
            
            # 定义回调函数
            def on_train_batch_end(trainer):
                try:
                    # YOLOv8 中总 batch 数通常存储在 trainer.nb 中
                    nb = getattr(trainer, 'nb', None)
                    if nb is None and hasattr(trainer, 'train_loader'):
                        nb = len(trainer.train_loader)
                    
                    if nb and nb > 0:
                        batch_p = (trainer.batch + 1) / nb
                        current_total_p = int((trainer.epoch + batch_p) * 100)
                        self.epoch_progress.emit(current_total_p, self.epochs * 100)
                except Exception:
                    pass

            def on_train_epoch_end(trainer):
                try:
                    curr_epoch = trainer.epoch + 1
                    self.epoch_progress.emit(curr_epoch * 100, self.epochs * 100)
                except Exception:
                    pass

            # 同时也尝试直接给 ultralytics 的内部 LOGGER 添加处理器
            try:
                from ultralytics.utils import LOGGER as ut_logger
                # 移除旧的 handler 防止重复
                for h in ut_logger.handlers[:]:
                    if isinstance(h, LogHandler):
                        ut_logger.removeHandler(h)
                ut_logger.addHandler(handler)
            except:
                pass

            try:
                # 确保 project_dir 是绝对路径且格式正确
                abs_project_dir = os.path.abspath(self.project_dir).replace("\\", "/")
                
                # 彻底禁用全局 settings 中的 runs_dir 影响，将其设为用户选择的目录
                try:
                    settings.update({
                        'datasets_dir': '',
                        'runs_dir': abs_project_dir
                    })
                except Exception as e:
                    print(f"Update settings failed: {e}")

                model = YOLO(self.model_path, task='detect')
                
                # 定义回调来检查停止标志
                def on_train_batch_start(trainer):
                    if not self.is_running:
                        raise Exception("Training stopped by user")

                model.add_callback("on_train_batch_start", on_train_batch_start)
                model.add_callback("on_train_batch_end", on_train_batch_end)
                model.add_callback("on_train_epoch_end", on_train_epoch_end)
                
                # 分离 project 和 name。
                # YOLOv8 最终输出路径是 project/name。
                # 如果我们要输出到 D:/Results，最好的办法是 project=D:/, name=Results
                project_path = os.path.dirname(abs_project_dir).replace("\\", "/")
                run_name = os.path.basename(abs_project_dir)
                
                # 如果 run_name 为空（说明选择了磁盘根目录），则必须指定名称
                if not run_name:
                    run_name = "train_output"
                
                model.train(
                    data=self.data_yaml,
                    epochs=self.epochs,
                    imgsz=self.imgsz,
                    workers=self.workers,
                    batch=self.batch,
                    cache=self.cache,
                    project=project_path,
                    name=run_name,
                    exist_ok=True,
                    patience=20, # 连续 20 轮无优化则停止
                    verbose=False # 关闭详细日志输出，仅显示每轮摘要
                )
            finally:
                # 无论成功失败，都移除处理器
                ultralytics_logger.removeHandler(handler)
                ultralytics_logger.propagate = True

            if self.is_running:
                self.finished.emit(True, "训练完成！")
            else:
                self.finished.emit(False, "训练已手动停止。")
        except Exception as e:
            if "Training stopped by user" in str(e):
                self.finished.emit(False, "训练已手动停止。")
            else:
                self.finished.emit(False, f"训练发生错误: {str(e)}")

class LabelSelectionDialog(QDialog):
    """自定义标签选择与输入对话框"""
    def __init__(self, current_label, all_labels, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择标签")
        self.setFixedWidth(300)
        self.result_label = None
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("输入标签名:"))
        self.search_edit = QLineEdit()
        self.search_edit.setText(current_label)
        self.search_edit.selectAll()
        layout.addWidget(self.search_edit)
        
        layout.addWidget(QLabel("现有标签列表:"))
        self.label_list = QListWidget()
        self.label_list.addItems(all_labels)
        # 选中当前标签
        items = self.label_list.findItems(current_label, Qt.MatchExactly)
        if items:
            self.label_list.setCurrentItem(items[0])
            
        self.label_list.itemClicked.connect(self._on_item_clicked)
        self.label_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.label_list)
        
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("确定")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)
        
        self.search_edit.returnPressed.connect(self.accept)

    def _on_item_clicked(self, item):
        """单击列表项：仅填充输入框，不关闭对话框"""
        self.search_edit.setText(item.text())

    def _on_item_double_clicked(self, item):
        """双击列表项：填充输入框并直接确认关闭"""
        self.search_edit.setText(item.text())
        self.accept()

    def get_label(self):
        return self.search_edit.text().strip()

class ExtractionThread(QThread):
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self, video_path, output_dir, mode, value):
        super().__init__()
        self.video_path = video_path
        self.output_dir = output_dir
        self.mode = mode
        self.value = value

    def run(self):
        success, message = VideoProcessor.extract_frames(
            self.video_path, self.output_dir, self.mode, self.value,
            callback=lambda c, t: self.progress.emit(c, t)
        )
        self.finished.emit(success, message)

class OptimizationThread(QThread):
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, source_dir, target_dir, imgsz):
        super().__init__()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.imgsz = imgsz

    def run(self):
        from utils.yolo_helper import YOLOHelper
        try:
            success = YOLOHelper.optimize_dataset(
                self.source_dir, 
                self.target_dir, 
                imgsz=self.imgsz,
                progress_callback=lambda p: self.progress.emit(p)
            )
            if success:
                self.finished.emit(True, "数据集优化完成！\n请使用优化后的目录进行训练，并记得在训练时设置相同的 imgsz。")
            else:
                self.finished.emit(False, "优化未完成，可能未找到有效标注数据。")
        except Exception as e:
            self.finished.emit(False, f"优化过程中发生错误: {e}")

class ExportTRTThread(QThread):
    progress = Signal(int)
    log_signal = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, model_path, imgsz, half=True):
        super().__init__()
        self.model_path = model_path
        self.imgsz = imgsz
        self.half = half

    def run(self):
        from ultralytics import YOLO
        import sys
        import io

        class StreamToSignal(io.TextIOBase):
            def __init__(self, signal):
                self.signal = signal
            def write(self, s):
                if s.strip():
                    self.signal.emit(s.strip())
                return len(s)

        # 保存原始 stdout
        old_stdout = sys.stdout
        sys.stdout = StreamToSignal(self.log_signal)

        try:
            self.log_signal.emit(f"开始导出模型: {os.path.basename(self.model_path)}")
            self.log_signal.emit(f"参数: imgsz={self.imgsz}, half={self.half}")
            self.log_signal.emit("提示: TensorRT 导出可能需要 3-10 分钟，请耐心等待...")
            
            model = YOLO(self.model_path, task='detect')
            # 执行导出
            export_path = model.export(
                format='engine',
                imgsz=self.imgsz,
                half=self.half,
                simplify=True,
                workspace=4
            )
            
            self.finished.emit(True, f"导出成功！模型已保存至:\n{export_path}")
        except Exception as e:
            self.finished.emit(False, f"导出失败: {str(e)}")
        finally:
            # 还原 stdout
            sys.stdout = old_stdout

class AutoAnnotationThread(QThread):
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, model_path, data_dir, conf_thres, device='cuda'):
        super().__init__()
        self.model_path = model_path
        self.data_dir = data_dir
        self.conf_thres = conf_thres
        self.device = device
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        from ultralytics import YOLO
        import cv2
        from utils.yolo_helper import YOLOHelper
        
        try:
            # 1. 加载模型
            model = YOLO(self.model_path)
            
            # 2. 扫描图片
            img_exts = ('.jpg', '.jpeg', '.png')
            images = [f for f in os.listdir(self.data_dir) if f.lower().endswith(img_exts)]
            total = len(images)
            
            if total == 0:
                self.finished.emit(False, "目录中没有图片")
                return

            # 3. 遍历推理
            count = 0
            for img_name in images:
                if not self.is_running:
                    break
                    
                img_path = os.path.join(self.data_dir, img_name)
                
                # 推理
                results = model.predict(
                    source=img_path,
                    conf=self.conf_thres,
                    device=self.device,
                    save=False,
                    verbose=False
                )
                
                # 解析结果
                boxes_to_save = []
                
                for r in results:
                    if r.boxes:
                        # 获取原始图片尺寸
                        h, w = r.orig_shape
                        
                        # r.boxes.data: (x1, y1, x2, y2, conf, cls)
                        det_data = r.boxes.data.cpu().numpy()
                        for row in det_data:
                            x1, y1, x2, y2, conf, cls = row
                            bw = x2 - x1
                            bh = y2 - y1
                            boxes_to_save.append([x1, y1, bw, bh, int(cls)])
                        
                        # 保存标签
                        label_name = os.path.splitext(img_name)[0] + ".txt"
                        label_path = os.path.join(self.data_dir, label_name)
                        YOLOHelper.save_labels(label_path, boxes_to_save, w, h)
                
                count += 1
                self.progress.emit(int(count / total * 100))
            
            self.finished.emit(True, f"自动标注完成！共处理 {count} 张图片。")
            
        except Exception as e:
            self.finished.emit(False, f"自动标注失败: {str(e)}")

class MainWindow(QMainWindow):
    def __init__(self, controller, config: ConfigManager):
        super().__init__()
        self.controller = controller
        self.config = config
        self.preview_window = None
        self.overlay_window = None
        self._loading_config = False
        
        self.setWindowTitle("AutoX - AI 控制中心")
        
        # 设置窗口大小：默认高度 880，若超过屏幕可用高度则自适应
        screen_geo = self.screen().availableGeometry()
        target_width = 1200
        target_height = min(880, screen_geo.height())
        self.resize(target_width, target_height)
        self.setMinimumWidth(800)
        
        self.setStyleSheet(MAIN_STYLE)
        
        self._init_ui()
        self._load_config_to_ui()
        
        # 排除在采集之外
        self._exclude_from_capture(self)
        
        # 状态更新定时器
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(500)

        # 预览更新定时器 (10ms)
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self._process_preview)
        self.preview_timer.start(10)

    def _init_ui(self):
        # 禁用菜单栏快捷键触发，防止 Alt 键卡住 GUI
        self.setMenuBar(None) 
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 选项卡控件
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tabs)
        
        # 1. 主控制选项卡
        self.control_tab = QWidget()
        self._init_control_tab()
        self.tabs.addTab(self.control_tab, "核心控制")
        
        # 2. 数据集工具选项卡
        self.tools_tab = QWidget()
        self._init_tools_tab()
        self.tabs.addTab(self.tools_tab, "数据集工具")

        # 3. 数据标注选项卡
        self.label_tab = QWidget()
        self._init_label_tab()
        self.tabs.addTab(self.label_tab, "数据标注")

        # 4. 模型管理选项卡
        self.model_tab = QWidget()
        self._init_model_tab()
        self.tabs.addTab(self.model_tab, "模型管理")
        
        self.game_tab = QWidget()
        self._init_game_tab()
        self.tabs.addTab(self.game_tab, "游戏中心")
        
        self.init_shortcuts()

    def init_shortcuts(self):
        """初始化全局快捷键"""
        # W: 切换标注模式
        self.shortcut_w = QShortcut(QKeySequence("W"), self)
        self.shortcut_w.activated.connect(self._shortcut_toggle_draw)
        
        # A: 上一张
        self.shortcut_a = QShortcut(QKeySequence("A"), self)
        self.shortcut_a.activated.connect(lambda: self._shortcut_navigate(-1))
        
        # D: 下一张
        self.shortcut_d = QShortcut(QKeySequence("D"), self)
        self.shortcut_d.activated.connect(lambda: self._shortcut_navigate(1))
        
        # Delete: 删除选中的框
        self.shortcut_del = QShortcut(QKeySequence("Delete"), self)
        self.shortcut_del.activated.connect(self._shortcut_delete_box)

    def _is_input_focused(self):
        """检查当前是否有输入框获得焦点"""
        focus_widget = self.focusWidget()
        if isinstance(focus_widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        return False

    def _shortcut_toggle_draw(self):
        if self.tabs.currentIndex() == 2 and not self._is_input_focused():
            self.btn_toggle_draw.setChecked(not self.btn_toggle_draw.isChecked())
            self._toggle_draw_mode()

    def _shortcut_navigate(self, delta):
        if self.tabs.currentIndex() == 2 and not self._is_input_focused():
            self._navigate_file(delta)

    def _shortcut_delete_box(self):
        if self.tabs.currentIndex() == 2 and not self._is_input_focused():
            idx = self.canvas.selected_idx
            if idx >= 0:
                self.canvas.boxes.pop(idx)
                self.canvas.selected_idx = -1
                self.canvas.update()
                self._update_box_list_ui()
                self._save_current_labels()

    def _init_control_tab(self):
        layout = QVBoxLayout(self.control_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # 1. 标题与状态
        header_layout = QHBoxLayout()
        title_label = QLabel("AutoX 控制中心")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        # 状态指示器
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: #d83b01; font-size: 14px; margin-right: 5px;")
        self.status_text = QLabel("系统未启动")
        self.status_text.setStyleSheet("color: #aaaaaa; font-weight: bold;")
        header_layout.addWidget(self.status_indicator)
        header_layout.addWidget(self.status_text)
        layout.addLayout(header_layout)

        # 2. 推理配置
        infer_group = QGroupBox("推理配置")
        infer_layout = QVBoxLayout(infer_group)
        infer_layout.setSpacing(12)
        infer_layout.setContentsMargins(12, 20, 12, 12)

        def create_row(label_text, widget, tooltip=None):
            row = QHBoxLayout()
            display_text = label_text
            if tooltip:
                display_text += " (?)"
            label = QLabel(display_text)
            if tooltip:
                label.setToolTip(tooltip)
                widget.setToolTip(tooltip)
            label.setFixedWidth(120)
            row.addWidget(label)
            
            # 设置控件为自动扩展
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(widget)
            return row

        # 置信度
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.1, 0.95)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.valueChanged.connect(self._on_config_changed)
        infer_layout.addLayout(create_row("置信度阈值", self.conf_spin, "只有 AI 判定目标的概率高于此值时才会触发锁定。值越高识别越严苛，越低越容易误识别。"))

        # FPS 限制
        self.max_fps_spin = QSpinBox()
        self.max_fps_spin.setRange(5, 60)
        self.max_fps_spin.setSingleStep(5)
        self.max_fps_spin.setSuffix(" FPS")
        self.max_fps_spin.valueChanged.connect(self._on_config_changed)
        infer_layout.addLayout(create_row("最高 FPS", self.max_fps_spin, "设置推理频率上限。最高 60 FPS，较高的 FPS 能提供更鲜活的图像，较低的 FPS 可以降低 CPU/GPU 负载。"))

        # 推理中心
        self.fov_center_combo = QComboBox()
        self.fov_center_combo.addItems(["屏幕中心", "鼠标位置"])
        self.fov_center_combo.currentIndexChanged.connect(self._on_config_changed)
        infer_layout.addLayout(create_row("推理中心", self.fov_center_combo, "选择推理区域和锁定范围的参考点。'屏幕中心'适合大多数第一人称射击游戏，'鼠标位置'适合 MOBA 或其他需要鼠标精准控制的游戏。"))

        # 启停键
        self.toggle_key_recorder = HotkeyRecorder(current_key="F9")
        self.toggle_key_recorder.key_changed.connect(self._on_config_changed)
        infer_layout.addLayout(create_row("全局启停键", self.toggle_key_recorder, "全局快捷键，用于在游戏内快速开启或停止系统运行。"))

        # 功能开关
        checks_layout = QHBoxLayout()
        self.debug_check = QCheckBox("显示调试窗口 (?)")
        self.debug_check.setToolTip("弹出一个独立的窗口显示当前的 AI 推理画面，包含识别框和锁定范围。")
        self.debug_check.stateChanged.connect(self._on_config_changed)
        
        self.overlay_check = QCheckBox("启用屏幕绘制 (?)")
        self.overlay_check.setToolTip("在屏幕顶层覆盖透明图层，直接绘制识别框，不影响鼠标操作。体验更佳。")
        self.overlay_check.stateChanged.connect(self._on_config_changed)
        
        self.fov_inference_check = QCheckBox("高精度局部推理 (?)")
        self.fov_inference_check.setToolTip("仅对准星或鼠标附近的区域进行推理。这能显著提升远距离小目标的识别率，并降低 CPU/GPU 负担。")
        self.fov_inference_check.stateChanged.connect(self._on_config_changed)
        
        checks_layout.addWidget(self.debug_check)
        checks_layout.addWidget(self.overlay_check)
        checks_layout.addWidget(self.fov_inference_check)
        infer_layout.addLayout(checks_layout)
        
        layout.addWidget(infer_group)

        # 3. 行为控制
        input_group = QGroupBox("行为控制")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(12)
        input_layout.setContentsMargins(12, 20, 12, 12)

        # 输入驱动选择
        self.input_method_combo = QComboBox()
        self.input_method_combo.addItems(["Syscall Input (推荐)", "Win32 Input (兼容)"])
        self.input_method_combo.currentIndexChanged.connect(self._on_input_method_changed)
        input_layout.addLayout(create_row("输入驱动", self.input_method_combo, "选择输入驱动类型。切换后需要重启程序生效。"))

        # 行为开关行
        behavior_checks = QHBoxLayout()
        self.auto_lock_check = QCheckBox("鼠标自动跟踪 (?)")
        self.auto_lock_check.setToolTip("开启后，无需按键即可自动跟踪并锁定视野内的目标。\n关闭后，需按住侧键/热键才会触发跟踪锁定。")
        self.auto_lock_check.stateChanged.connect(self._on_config_changed)
        
        self.human_curve_check = QCheckBox("模拟人类曲线 (?)")
        self.human_curve_check.setToolTip("开启后，鼠标将模拟人类随机曲线轨迹移动，更具欺骗性。")
        self.human_curve_check.stateChanged.connect(self._on_config_changed)
        
        behavior_checks.addWidget(self.auto_lock_check)
        behavior_checks.addWidget(self.human_curve_check)
        input_layout.addLayout(behavior_checks)

        # 移动触发键
        self.move_key_recorder = HotkeyRecorder(current_key="RButton")
        self.move_key_recorder.key_changed.connect(self._on_config_changed)
        input_layout.addLayout(create_row("移动触发键", self.move_key_recorder, "未开启自动跟踪时，需按住此键触发锁定。"))

        # 范围与偏移行 (User Request: Move offset to same row as fov, split equally)
        fov_offset_layout = QHBoxLayout()
        
        # 左侧：推理范围
        fov_sub_layout = QHBoxLayout()
        fov_label = QLabel("推理范围 (?)")
        fov_label.setToolTip("AI 进行识别的区域大小。范围越大识别越多，但会增加计算负担。")
        fov_label.setFixedWidth(80)
        self.fov_spin = QDoubleSpinBox()
        self.fov_spin.setRange(50, 2000)
        self.fov_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.fov_spin.setToolTip("AI 进行识别的区域大小。范围越大识别越多，但会增加计算负担。")
        self.fov_spin.valueChanged.connect(self._on_config_changed)
        fov_sub_layout.addWidget(fov_label)
        fov_sub_layout.addWidget(self.fov_spin)
        
        # 右侧：目标偏移半径
        offset_sub_layout = QHBoxLayout()
        offset_label = QLabel("目标偏移半径 (?)")
        offset_label.setToolTip("0表示锁定中心点。大于0则在中心点指定半径的圆内随机偏移。")
        offset_label.setFixedWidth(110)
        offset_label.setStyleSheet("margin-left: 10px;")
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(0, 100)
        self.offset_spin.setSuffix(" px")
        self.offset_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.offset_spin.setToolTip("0表示锁定中心点。大于0则在中心点指定半径的圆内随机偏移。")
        self.offset_spin.valueChanged.connect(self._on_config_changed)
        offset_sub_layout.addWidget(offset_label)
        offset_sub_layout.addWidget(self.offset_spin)
        
        fov_offset_layout.addLayout(fov_sub_layout)
        fov_offset_layout.addLayout(offset_sub_layout)
        input_layout.addLayout(fov_offset_layout)

        # 移动速度行
        speed_layout = QHBoxLayout()
        speed_label = QLabel("移动速度 (?)")
        speed_label.setToolTip("设置鼠标移动到目标的速度。'极快'为瞬移，其他模式会平滑过渡。")
        speed_label.setFixedWidth(80)
        self.move_speed_combo = QComboBox()
        self.move_speed_combo.addItems(["极快", "快速", "正常", "慢速", "自定义(ms)"])
        self.move_speed_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.move_speed_combo.setToolTip("设置鼠标移动到目标的速度。'极快'为瞬移，其他模式会平滑过渡。")
        self.move_speed_combo.currentIndexChanged.connect(self._on_config_changed)
        
        self.custom_speed_spin = QSpinBox()
        self.custom_speed_spin.setRange(1, 500)
        self.custom_speed_spin.setSuffix("ms")
        self.custom_speed_spin.setFixedWidth(80)
        self.custom_speed_spin.setVisible(False)
        self.custom_speed_spin.valueChanged.connect(self._on_config_changed)
        
        self.custom_random_label = QLabel("±")
        self.custom_random_label.setVisible(False)
        
        self.custom_random_spin = QSpinBox()
        self.custom_random_spin.setRange(0, 100)
        self.custom_random_spin.setSuffix("ms")
        self.custom_random_spin.setFixedWidth(80)
        self.custom_random_spin.setVisible(False)
        self.custom_random_spin.valueChanged.connect(self._on_config_changed)
        
        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.move_speed_combo)
        speed_layout.addWidget(self.custom_speed_spin)
        speed_layout.addWidget(self.custom_random_label)
        speed_layout.addWidget(self.custom_random_spin)
        input_layout.addLayout(speed_layout)

        # 鼠标灵敏度
        self.sensitivity_spin = QDoubleSpinBox()
        self.sensitivity_spin.setRange(0.01, 10.0)
        self.sensitivity_spin.setSingleStep(0.1)
        self.sensitivity_spin.setValue(1.0)
        self.sensitivity_spin.setDecimals(2)
        self.sensitivity_spin.setToolTip("鼠标移动的灵敏度倍率。用于适配不同游戏的鼠标灵敏度设置。如果画面移动不足，请调大；如果移动过度，请调小。")
        self.sensitivity_spin.valueChanged.connect(self._on_config_changed)
        input_layout.addLayout(create_row("鼠标灵敏度", self.sensitivity_spin, "鼠标移动的灵敏度倍率。"))

        # 移动后执行
        self.post_action_recorder = HotkeyRecorder(current_key="")
        self.post_action_recorder.key_changed.connect(self._on_config_changed)
        input_layout.addLayout(create_row("移动后执行", self.post_action_recorder, "鼠标移动到目标位置后自动执行的操作，例如自动开火。可以是鼠标键或组合键。"))

        # 执行次数与间隔
        post_action_params_layout = QHBoxLayout()
        
        # 左侧：执行次数
        count_sub_layout = QHBoxLayout()
        count_label = QLabel("执行次数 (?)")
        count_label.setToolTip("移动到目标位置后，后置操作执行的次数。例如设置为 10 可实现自动连发。")
        count_label.setFixedWidth(80)
        self.post_action_count_spin = QSpinBox()
        self.post_action_count_spin.setRange(1, 100)
        self.post_action_count_spin.setValue(1)
        self.post_action_count_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.post_action_count_spin.valueChanged.connect(self._on_config_changed)
        count_sub_layout.addWidget(count_label)
        count_sub_layout.addWidget(self.post_action_count_spin)
        
        # 右侧：执行间隔
        interval_sub_layout = QHBoxLayout()
        interval_label = QLabel("执行间隔 (?)")
        interval_label.setToolTip("多次执行之间的间隔时间（毫秒）。")
        interval_label.setFixedWidth(80)
        interval_label.setStyleSheet("margin-left: 10px;")
        self.post_action_interval_spin = QSpinBox()
        self.post_action_interval_spin.setRange(20, 1000)
        self.post_action_interval_spin.setValue(20)
        self.post_action_interval_spin.setSuffix(" ms")
        self.post_action_interval_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.post_action_interval_spin.valueChanged.connect(self._on_config_changed)
        interval_sub_layout.addWidget(interval_label)
        interval_sub_layout.addWidget(self.post_action_interval_spin)
        
        post_action_params_layout.addLayout(count_sub_layout)
        post_action_params_layout.addLayout(interval_sub_layout)
        input_layout.addLayout(post_action_params_layout)


        layout.addWidget(input_group)

        # 4. 控制按钮
        layout.addStretch()
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        self.start_btn = QPushButton("启动系统")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.setFixedHeight(45)
        self.start_btn.clicked.connect(self._start_clicked)
        
        self.stop_btn = QPushButton("停止运行")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setFixedHeight(45)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_clicked)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)


    def _init_tools_tab(self):
        layout = QVBoxLayout(self.tools_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        title = QLabel("视频抽帧工具")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        # 文件选择
        file_group = QGroupBox("文件与目录")
        file_layout = QVBoxLayout(file_group)
        
        v_layout = QHBoxLayout()
        self.video_path_edit = QLineEdit()
        self.video_path_edit.setPlaceholderText("选择视频文件...")
        btn_browse_video = QPushButton("浏览")
        btn_browse_video.clicked.connect(self._browse_video)
        v_layout.addWidget(self.video_path_edit)
        v_layout.addWidget(btn_browse_video)
        file_layout.addLayout(v_layout)

        o_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("选择保存目录...")
        btn_browse_output = QPushButton("浏览")
        btn_browse_output.clicked.connect(self._browse_output)
        o_layout.addWidget(self.output_dir_edit)
        o_layout.addWidget(btn_browse_output)
        file_layout.addLayout(o_layout)
        layout.addWidget(file_group)

        # 抽帧设置
        settings_group = QGroupBox("抽取设置")
        settings_layout = QVBoxLayout(settings_group)
        
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("模式:"))
        self.extract_mode_combo = QComboBox()
        self.extract_mode_combo.addItems(["按总张数抽取", "按时间间隔抽取"])
        mode_layout.addWidget(self.extract_mode_combo)
        settings_layout.addLayout(mode_layout)

        val_layout = QHBoxLayout()
        self.extract_val_label = QLabel("抽取张数:")
        self.extract_val_spin = QDoubleSpinBox()
        self.extract_val_spin.setRange(1, 10000)
        self.extract_val_spin.setValue(100)
        val_layout.addWidget(self.extract_val_label)
        val_layout.addWidget(self.extract_val_spin)
        settings_layout.addLayout(val_layout)
        
        self.extract_mode_combo.currentIndexChanged.connect(self._update_extract_ui)
        layout.addWidget(settings_group)

        # 小目标数据集优化工具
        opt_group = QGroupBox("小目标数据集优化 (裁剪以放大目标)")
        opt_layout = QVBoxLayout(opt_group)
        
        opt_desc = QLabel("方案：以标注框为中心裁剪 imgsz 大小的区域，从而在训练时“放大”目标。")
        opt_desc.setStyleSheet("color: #ffffff; font-size: 12px;")
        opt_layout.addWidget(opt_desc)

        opt_input_layout = QHBoxLayout()
        opt_label = QLabel("目标训练分辨率 (imgsz) (?)")
        opt_tooltip = "选择您计划在训练时使用的图像尺寸。裁剪工具会生成此尺寸的图片，确保训练时不进行缩放，最大限度保留细节。"
        opt_label.setToolTip(opt_tooltip)
        opt_input_layout.addWidget(opt_label)
        
        self.opt_imgsz_combo = QComboBox()
        self.opt_imgsz_combo.addItems(["640", "960", "1280"])
        self.opt_imgsz_combo.setCurrentText("640")
        self.opt_imgsz_combo.setToolTip(opt_tooltip)
        opt_input_layout.addWidget(self.opt_imgsz_combo)
        opt_layout.addLayout(opt_input_layout)

        self.btn_optimize_dataset = QPushButton("开始优化数据集 (裁剪原图) (?)")
        self.btn_optimize_dataset.setToolTip("自动扫描所有标注框，并以框为中心裁剪出固定大小的区域。这能让小目标在模型眼中变得‘巨大’，从而极大地提升训练效果。")
        self.btn_optimize_dataset.clicked.connect(self._start_dataset_optimization)
        opt_layout.addWidget(self.btn_optimize_dataset)
        
        layout.addWidget(opt_group)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        # 执行按钮
        self.extract_btn = QPushButton("开始抽取图片")
        self.extract_btn.setFixedHeight(45)
        self.extract_btn.clicked.connect(self._start_extraction)
        layout.addWidget(self.extract_btn)

    def _init_game_tab(self):
        layout = QVBoxLayout(self.game_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        title = QLabel("游戏中心")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        # 后坐力抑制配置组
        recoil_group = QGroupBox("后坐力抑制 (Recoil Control)")
        recoil_layout = QVBoxLayout(recoil_group)
        recoil_layout.setSpacing(12)
        recoil_layout.setContentsMargins(12, 20, 12, 12)

        def create_row(label_text, widget, tooltip=None):
            row = QHBoxLayout()
            label = QLabel(label_text)
            if tooltip:
                label.setToolTip(tooltip)
                widget.setToolTip(tooltip)
            label.setFixedWidth(140)
            row.addWidget(label)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row.addWidget(widget)
            return row

        # 1. 功能开关
        self.recoil_check = QCheckBox("启用后坐力抑制 (?)")
        self.recoil_check.setToolTip("当程序接管准星且正在开火时，自动注入向下补偿量以抵消武器后坐力。")
        self.recoil_check.stateChanged.connect(self._on_config_changed)
        recoil_layout.addWidget(self.recoil_check)

        # 2. 抑制强度
        self.recoil_strength_spin = QSpinBox()
        self.recoil_strength_spin.setRange(0, 100)
        self.recoil_strength_spin.setSuffix(" px/frame")
        self.recoil_strength_spin.valueChanged.connect(self._on_config_changed)
        recoil_layout.addLayout(create_row("抑制强度", self.recoil_strength_spin, "调整向下压枪的力度（像素/帧）。0 为无效果，100 为超强压枪（适用于高分辨率或极大后坐力）。"))

        # 3. 随机抖动
        self.recoil_jitter_spin = QDoubleSpinBox()
        self.recoil_jitter_spin.setRange(0.0, 2.0)
        self.recoil_jitter_spin.setSingleStep(0.1)
        self.recoil_jitter_spin.setDecimals(1)
        self.recoil_jitter_spin.valueChanged.connect(self._on_config_changed)
        recoil_layout.addLayout(create_row("水平随机抖动", self.recoil_jitter_spin, "在压枪时注入少许水平方向的随机移动，使动作看起来更像人类玩家。"))

        layout.addWidget(recoil_group)

        # 运动补偿与预判配置组
        motion_group = QGroupBox("运动增强 (Motion Enhancement)")
        motion_layout = QVBoxLayout(motion_group)
        motion_layout.setSpacing(12)
        motion_layout.setContentsMargins(12, 20, 12, 12)

        # 2. 移动补偿
        self.move_comp_check = QCheckBox("启用我方移动补偿")
        self.move_comp_check.setToolTip("检测 WASD 按键。当您在走动时，自动抵消准星因位移产生的视觉晃动。")
        self.move_comp_check.stateChanged.connect(self._on_config_changed)
        motion_layout.addWidget(self.move_comp_check)

        self.move_comp_strength_spin = QDoubleSpinBox()
        self.move_comp_strength_spin.setRange(0.0, 5.0)
        self.move_comp_strength_spin.setSingleStep(0.1)
        self.move_comp_strength_spin.setDecimals(1)
        self.move_comp_strength_spin.valueChanged.connect(self._on_config_changed)
        
        strength_tooltip = (
            "调整 WASD 移动时的反向补偿力度。\n"
            "数值越大，补偿越强（光标移动越快）。\n"
            "- 1.0: 弱补偿 (适合步枪点射)\n"
            "- 2.0: 中等补偿 (默认，适合大多数情况)\n"
            "- 3.0+: 强补偿 (适合近距离冲锋)"
        )
        motion_layout.addLayout(create_row("补偿强度 (推荐 1.0-3.0)", self.move_comp_strength_spin, strength_tooltip))

        layout.addWidget(motion_group)
        layout.addStretch()

    def _update_extract_ui(self):
        if self.extract_mode_combo.currentIndex() == 0:
            self.extract_val_label.setText("抽取张数:")
            self.extract_val_spin.setDecimals(0)
            self.extract_val_spin.setValue(100)
        else:
            self.extract_val_label.setText("间隔时间 (秒):")
            self.extract_val_spin.setDecimals(1)
            self.extract_val_spin.setValue(1.0)

    def _browse_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", "Video Files (*.mp4 *.avi *.mkv *.mov)")
        if path:
            self.video_path_edit.setText(path)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if path:
            self.output_dir_edit.setText(path)

    def _start_extraction(self):
        video_path = self.video_path_edit.text()
        output_dir = self.output_dir_edit.text()
        
        if not video_path or not output_dir:
            QMessageBox.warning(self, "提示", "请先选择视频文件和保存目录")
            return

        mode = 'count' if self.extract_mode_combo.currentIndex() == 0 else 'interval'
        value = self.extract_val_spin.value()

        self.extract_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.thread = ExtractionThread(video_path, output_dir, mode, value)
        self.thread.progress.connect(self._update_progress)
        self.thread.finished.connect(self._on_extraction_finished)
        self.thread.start()

    def _update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_extraction_finished(self, success, message):
        self.extract_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        if success:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.critical(self, "错误", message)

    def _start_dataset_optimization(self):
        """执行数据集优化裁剪"""
        # 使用当前正在标注的目录作为默认源
        source_dir = self.current_dir
        if not source_dir:
            source_dir = QFileDialog.getExistingDirectory(self, "选择待优化的数据集目录 (包含图片和 .txt)")
            if not source_dir: return

        target_dir = QFileDialog.getExistingDirectory(self, "选择优化后的保存目录 (建议为空目录)")
        if not target_dir: return
        
        if os.path.abspath(source_dir) == os.path.abspath(target_dir):
            QMessageBox.critical(self, "错误", "保存目录不能与源目录相同！")
            return

        imgsz = int(self.opt_imgsz_combo.currentText())
        
        msg = f"该工具将扫描目录下的所有标注，并以标注框为中心裁剪出 {imgsz}x{imgsz} 的区域。\n" \
              f"这会使小目标在训练时看起来更大，从而提升识别效果。\n\n" \
              f"源目录: {source_dir}\n" \
              f"目标目录: {target_dir}\n\n" \
              f"是否开始？"
        
        if QMessageBox.question(self, "确认优化", msg) != QMessageBox.Yes:
            return

        self.btn_optimize_dataset.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)

        self.opt_thread = OptimizationThread(source_dir, target_dir, imgsz)
        self.opt_thread.progress.connect(self.progress_bar.setValue)
        self.opt_thread.finished.connect(self._on_optimization_finished)
        self.opt_thread.start()

    def _on_optimization_finished(self, success, message):
        self.btn_optimize_dataset.setEnabled(True)
        self.progress_bar.setVisible(False)
        if success:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.critical(self, "错误", message)

    def _load_config_to_ui(self):
        # 暂时设置加载标志，防止初始化 UI 时触发 _on_config_changed 导致配置被错误覆盖
        self._loading_config = True
        
        self.conf_spin.setValue(self.config.get("inference.conf_thres"))
        self.max_fps_spin.setValue(self.config.get("inference.max_fps", 60))
        self.debug_check.setChecked(self.config.get("gui.show_debug"))
        self.overlay_check.setChecked(False) # 默认不开启，避免遮挡
        self.fov_inference_check.setChecked(self.config.get("inference.use_fov_inference", False))
        center_mode = self.config.get("inference.fov_center_mode", "screen")
        self.fov_center_combo.setCurrentText("屏幕中心" if center_mode == "screen" else "鼠标位置")
        
        self.toggle_key_recorder.set_key(self.config.get("input.toggle_key", "F9"))
        self.move_key_recorder.set_key(self.config.get("input.move_key", "RButton"))
        
        # 输入驱动加载
        input_method = self.config.get("input.input_method", "syscall")
        method_map = {"syscall": 0, "win32": 1}
        self.input_method_combo.setCurrentIndex(method_map.get(input_method, 0))

        # 行为设置加载
        self.auto_lock_check.setChecked(self.config.get("input.auto_lock", True))
        self.fov_spin.setValue(self.config.get("input.fov", 500))
        
        move_speed = self.config.get("input.move_speed", "normal")
        speed_map = {"fast": "极快", "fast_medium": "快速", "normal": "正常", "slow": "慢速", "custom": "自定义(ms)"}
        idx = self.move_speed_combo.findText(speed_map.get(move_speed, "正常"))
        if idx >= 0: self.move_speed_combo.setCurrentIndex(idx)
        
        self.custom_speed_spin.setValue(self.config.get("input.custom_speed_ms", 10))
        self.custom_random_spin.setValue(self.config.get("input.custom_speed_random", 5))
        self.human_curve_check.setChecked(self.config.get("input.human_curve", False))
        self.offset_spin.setValue(self.config.get("input.offset_radius", 0))
        self.sensitivity_spin.setValue(self.config.get("input.mouse_sensitivity", 1.0))
        self.post_action_recorder.set_key(self.config.get("input.post_action", ""))
        self.post_action_count_spin.setValue(self.config.get("input.post_action_count", 1))
        self.post_action_interval_spin.setValue(self.config.get("input.post_action_interval_ms", 10))

        # 后坐力设置加载
        self.recoil_check.setChecked(self.config.get("input.recoil_enabled", False))
        # 强度直接 1:1 映射
        raw_strength = self.config.get("input.recoil_strength", 2.0)
        self.recoil_strength_spin.setValue(int(raw_strength))
        self.recoil_jitter_spin.setValue(self.config.get("input.recoil_x_jitter", 0.5))

        # 运动增强设置加载
        self.move_comp_check.setChecked(self.config.get("input.move_comp_enabled", False))
        self.move_comp_strength_spin.setValue(self.config.get("input.move_comp_strength", 1.0))

        # 恢复加载标志
        self._loading_config = False
        
        # 确保初始化时同步配置到 Controller
        self._on_config_changed()

        # 启动全局热键轮询定时器
        self.toggle_timer = QTimer(self)
        self.toggle_timer.timeout.connect(self._check_global_toggle)
        self.toggle_timer.start(30) # 30ms 检测一次 (提高响应速度)
        self._last_toggle_state = False

    def _check_global_toggle(self):
        """轮询全局启停快捷键"""
        # 检查全局启停快捷键 (toggle_key)
        key = self.toggle_key_recorder.get_key()
        if not key:
            return
            
        is_pressed = is_hotkey_pressed(key)
        
        # 边缘检测：按下时触发一次
        if is_pressed and not self._last_toggle_state:
            if self.controller and self.controller.running:
                self._stop_clicked()
                print(f"[System] 快捷键 {key} 触发停止")
            else:
                self._start_clicked()
                print(f"[System] 快捷键 {key} 触发启动")
                
        self._last_toggle_state = is_pressed

    def _on_input_method_changed(self, index):
        if self._loading_config:
            return
        
        self._on_config_changed()
        
        QMessageBox.information(
            self, 
            "需重启生效", 
            "输入驱动已切换。程序即将关闭，请手动重新启动以应用更改。",
            QMessageBox.Ok
        )
        
        # 关闭程序
        if hasattr(self, 'controller'):
            self.controller.stop()
        
        # 使用 quit() 退出应用程序，触发 main.py 中的清理流程
        QApplication.instance().quit()

    def _on_config_changed(self):
        if self._loading_config:
            return
            
        conf_val = self.conf_spin.value()
        max_fps_val = self.max_fps_spin.value()
        debug_val = self.debug_check.isChecked()
        overlay_val = self.overlay_check.isChecked()
        fov_inf_val = self.fov_inference_check.isChecked()
        
        center_mode_val = "screen" if self.fov_center_combo.currentText() == "屏幕中心" else "mouse"
        
        trigger_mode_val = "manual"
        toggle_key_val = self.toggle_key_recorder.get_key()
        move_key_val = self.move_key_recorder.get_key()
# 获取输入驱动
        method_idx = self.input_method_combo.currentIndex()
        input_method_val = "syscall"
        if method_idx == 1:
            input_method_val = "win32"
        
        # 行为设置获取
        auto_lock_val = self.auto_lock_check.isChecked()
        fov_val = self.fov_spin.value()
        
        speed_text = self.move_speed_combo.currentText()
        speed_map_rev = {"极快": "fast", "快速": "fast_medium", "正常": "normal", "慢速": "slow", "自定义(ms)": "custom"}
        move_speed_val = speed_map_rev.get(speed_text, "normal")
        
        # 控制自定义速度输入框可见性
        is_custom = (speed_text == "自定义(ms)")
        self.custom_speed_spin.setVisible(is_custom)
        self.custom_random_label.setVisible(is_custom)
        self.custom_random_spin.setVisible(is_custom)
        
        custom_speed_val = self.custom_speed_spin.value()
        custom_random_val = self.custom_random_spin.value()
        
        human_curve_val = self.human_curve_check.isChecked()
        offset_val = self.offset_spin.value()
        sensitivity_val = self.sensitivity_spin.value()
        post_action_val = self.post_action_recorder.get_key()
        post_action_count_val = self.post_action_count_spin.value()
        post_action_interval_ms_val = self.post_action_interval_spin.value()

        # 后坐力设置获取
        recoil_enabled_val = self.recoil_check.isChecked()
        # 直接 1:1 映射 (0-10)
        recoil_strength_val = float(self.recoil_strength_spin.value())
        recoil_jitter_val = self.recoil_jitter_spin.value()

        # 运动增强设置获取
        move_comp_enabled_val = self.move_comp_check.isChecked()
        move_comp_strength_val = self.move_comp_strength_spin.value()

        # 保存到配置
        self.config.set("inference.conf_thres", conf_val)
        self.config.set("inference.max_fps", max_fps_val)
        self.config.set("gui.show_debug", debug_val)
        self.config.set("inference.use_fov_inference", fov_inf_val)
        self.config.set("inference.fov_center_mode", center_mode_val)
        self.config.set("input.trigger_mode", trigger_mode_val)
        self.config.set("input.toggle_key", toggle_key_val)
        self.config.set("input.move_key", move_key_val)
        self.config.set("input.input_method", input_method_val)
        
        self.config.set("input.auto_lock", auto_lock_val)
        self.config.set("input.fov", fov_val)
        self.config.set("input.move_speed", move_speed_val)
        self.config.set("input.custom_speed_ms", custom_speed_val)
        self.config.set("input.custom_speed_random", custom_random_val)
        self.config.set("input.human_curve", human_curve_val)
        self.config.set("input.offset_radius", offset_val)
        self.config.set("input.mouse_sensitivity", sensitivity_val)
        self.config.set("input.post_action", post_action_val)
        self.config.set("input.post_action_count", post_action_count_val)
        self.config.set("input.post_action_interval_ms", post_action_interval_ms_val)
        
        # 后坐力配置保存
        self.config.set("input.recoil_enabled", recoil_enabled_val)
        self.config.set("input.recoil_strength", recoil_strength_val)
        self.config.set("input.recoil_x_jitter", recoil_jitter_val)
        
        # 运动增强配置保存
        self.config.set("input.move_comp_enabled", move_comp_enabled_val)
        self.config.set("input.move_comp_strength", move_comp_strength_val)
        
        # 同步到控制器
        if self.controller:
            if hasattr(self.controller, 'inference'):
                self.controller.inference.conf_thres = conf_val
            else:
                self.controller.conf_thres = conf_val
                
            self.controller.max_fps = max_fps_val
            self.controller.show_debug = debug_val
            self.controller.use_fov_inference = fov_inf_val
            self.controller.fov_center_mode = center_mode_val
            self.controller.move_key = move_key_val
            
            # 行为设置同步
            self.controller.auto_lock = auto_lock_val
            self.controller.fov_size = fov_val
            self.controller.move_speed = move_speed_val
            self.controller.custom_speed_ms = custom_speed_val
            self.controller.custom_speed_random = custom_random_val
            self.controller.human_curve = human_curve_val
            self.controller.offset_radius = offset_val
            self.controller.mouse_sensitivity = sensitivity_val
            self.controller.post_action = post_action_val
            self.controller.post_action_count = post_action_count_val
            self.controller.post_action_interval = post_action_interval_ms_val / 1000.0

            # 后坐力同步
            self.controller.recoil_enabled = recoil_enabled_val
            self.controller.recoil_strength = recoil_strength_val
            self.controller.recoil_x_jitter = recoil_jitter_val

            # 运动增强同步
            self.controller.move_comp_enabled = move_comp_enabled_val
            self.controller.move_comp_strength = move_comp_strength_val

    def _update_status(self):
        if self.controller and self.controller.running:
            self.status_indicator.setStyleSheet("color: #107c10; font-size: 18px;")
            self.status_text.setText("系统运行中")
        else:
            self.status_indicator.setStyleSheet("color: #d83b01; font-size: 18px;")
            self.status_text.setText("系统已停止")
            
        # 更新按钮状态
        is_running = self.controller and self.controller.running
        self.start_btn.setEnabled(not is_running)
        self.stop_btn.setEnabled(is_running)
        self.start_btn.setText("启动系统")

    def _process_preview(self):
        """处理预览窗口和Overlay更新"""
        show_debug = self.debug_check.isChecked()
        show_overlay = self.overlay_check.isChecked()
        
        # 只要有一个需要显示，就确保 Controller 开启 debug 模式
        if self.controller:
            self.controller.show_debug = (show_debug or show_overlay)

        if self.controller and (show_debug or show_overlay):
            # 1. 确保窗口状态正确
            # 预览窗口
            if show_debug:
                if self.preview_window is None:
                    self.preview_window = PreviewWindow(self)
                    self.preview_window.show()
                    self._exclude_from_capture(self.preview_window)
            else:
                if self.preview_window is not None:
                    self.preview_window.close()
                    self.preview_window = None

            # Overlay 窗口
            if show_overlay:
                if self.overlay_window is None:
                    self.overlay_window = OverlayWindow()
                    self.overlay_window.show()
                    self._exclude_from_capture(self.overlay_window)
            else:
                if self.overlay_window is not None:
                    self.overlay_window.close()
                    self.overlay_window = None
            
            # 2. 从队列获取最新数据包
            debug_data = None
            try:
                while not self.controller.debug_queue.empty():
                    debug_data = self.controller.debug_queue.get_nowait()
            except Exception:
                pass
            
            if debug_data is not None:
                # debug_data = {'frame': frame, 'results': results, 'target': target, 'center': (cx, cy), 'fov_size': fov}
                frame = debug_data['frame']
                results = debug_data['results']
                target = debug_data['target']
                center = debug_data['center']
                fov_size = debug_data['fov_size']

                # 更新预览窗口 (需要画框)
                if self.preview_window:
                    # 使用 QPainter 在原始帧上绘图，替代 cv2
                    # 此时的 frame 是纯净的 BGR numpy 数组
                    disp_frame = frame.copy()
                    
                    # 将 numpy 数组转为 QImage 方便 QPainter 操作 (或者传递原始数据给 PreviewWindow 处理)
                    # 这里为了简化，我们先直接把数据传给 update_frame_with_data，在窗口内部绘制
                    
                    # 构造绘制数据
                    draw_data = {
                        'fov_center': center,
                        'fov_radius': fov_size / 2,
                        'results': results,
                        'target': target,
                        'fps': debug_data.get('fps', 0)
                    }
                    
                    self.preview_window.update_frame_with_data(disp_frame, draw_data)

                # 更新 Overlay
                if self.overlay_window:
                    self.overlay_window.update_data(results, target, center, fov_size / 2, debug_data.get('fps', 0))
        else:
            # 全部关闭
            if self.preview_window is not None:
                self.preview_window.close()
                self.preview_window = None
            if self.overlay_window is not None:
                self.overlay_window.close()
                self.overlay_window = None

    def _exclude_from_capture(self, window):
        """设置窗口不被截屏软件捕捉"""
        try:
            hwnd = window.winId()
            # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (Win10 2004+)
            if not ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011):
                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000001)
        except Exception as e:
            print(f"Exclude from capture failed: {e}")

    def _init_label_tab(self):
        main_layout = QHBoxLayout(self.label_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 创建主分割条
        self.label_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.label_splitter)

        # 1. 左侧：图片文件列表
        left_widget = QWidget()
        left_column = QVBoxLayout(left_widget)
        left_column.setContentsMargins(5, 5, 5, 5)
        left_column.addWidget(QLabel("图片列表:"))
        self.file_list = QListWidget()
        self.file_list.setMinimumWidth(150)
        self.file_list.itemClicked.connect(self._on_file_selected)
        left_column.addWidget(self.file_list)
        self.label_splitter.addWidget(left_widget)

        # 2. 中间：标注画布
        mid_widget = QWidget()
        mid_column = QVBoxLayout(mid_widget)
        mid_column.setContentsMargins(5, 5, 5, 5)
        
        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 5, 0, 5)
        
        btn_open_dir = QPushButton("打开目录")
        btn_open_dir.setFixedWidth(80)
        btn_open_dir.setFixedHeight(26)
        btn_open_dir.setStyleSheet("font-size: 12px; padding: 0; margin: 0;")
        btn_open_dir.clicked.connect(self._label_open_dir)
        toolbar.addWidget(btn_open_dir)

        toolbar.addSpacing(8)
        self.btn_organize = QPushButton("整理")
        self.btn_organize.setFixedWidth(60)
        self.btn_organize.setFixedHeight(26)
        self.btn_organize.setStyleSheet("font-size: 12px; padding: 0; margin: 0; background-color: #0078d4;")
        self.btn_organize.clicked.connect(self._label_organize_dataset)
        toolbar.addWidget(self.btn_organize)

        toolbar.addSpacing(8)
        self.btn_auto_label = QPushButton("自动标注")
        self.btn_auto_label.setFixedWidth(80)
        self.btn_auto_label.setFixedHeight(26)
        self.btn_auto_label.setStyleSheet("font-size: 12px; padding: 0; margin: 0; background-color: #6a00ff;")
        self.btn_auto_label.clicked.connect(self._label_auto_annotate)
        toolbar.addWidget(self.btn_auto_label)

        toolbar.addSpacing(15)
        self.btn_toggle_draw = QPushButton("标注(W)")
        self.btn_toggle_draw.setCheckable(True)
        self.btn_toggle_draw.setFixedWidth(80)
        self.btn_toggle_draw.setFixedHeight(26)
        self.btn_toggle_draw.setStyleSheet("font-size: 12px; padding: 0; margin: 0;")
        self.btn_toggle_draw.clicked.connect(self._toggle_draw_mode)
        toolbar.addWidget(self.btn_toggle_draw)

        toolbar.addSpacing(8)
        self.btn_prev = QPushButton("上一张(A)")
        self.btn_prev.setFixedWidth(80)
        self.btn_prev.setFixedHeight(26)
        self.btn_prev.setStyleSheet("font-size: 12px; padding: 0; margin: 0;")
        self.btn_prev.clicked.connect(lambda: self._navigate_file(-1))
        toolbar.addWidget(self.btn_prev)

        toolbar.addSpacing(8)
        self.btn_next = QPushButton("下一张(D)")
        self.btn_next.setFixedWidth(80)
        self.btn_next.setFixedHeight(26)
        self.btn_next.setStyleSheet("font-size: 12px; padding: 0; margin: 0;")
        self.btn_next.clicked.connect(lambda: self._navigate_file(1))
        toolbar.addWidget(self.btn_next)
        
        toolbar.addSpacing(15)
        self.label_info = QLabel("未选择目录")
        self.label_info.setStyleSheet("font-size: 12px;")
        toolbar.addWidget(self.label_info)
        toolbar.addStretch()
        mid_column.addLayout(toolbar)

        # 画布
        self.canvas = LabelingCanvas()
        self.canvas.box_added.connect(self._on_box_added)
        self.canvas.box_selected.connect(self._on_box_selected_on_canvas)
        self.canvas.box_deleted.connect(self._on_box_deleted_on_canvas)
        self.canvas.box_edit_requested.connect(self._on_box_edit_requested)
        mid_column.addWidget(self.canvas, 1)
        
        self.label_splitter.addWidget(mid_widget)

        # 3. 右侧：标签与框管理
        right_widget = QWidget()
        right_main_layout = QVBoxLayout(right_widget)
        right_main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.right_splitter = QSplitter(Qt.Vertical)
        
        # --- 上部分：标签管理 ---
        label_manage_container = QWidget()
        label_manage_layout = QVBoxLayout(label_manage_container)
        label_manage_layout.setContentsMargins(5, 5, 5, 5)
        
        label_manage_layout.addWidget(QLabel("标签管理 (classes.txt):"))
        self.class_list = QListWidget()
        # 移除固定高度，允许分割条调整
        self.class_list.currentRowChanged.connect(self._on_class_changed)
        label_manage_layout.addWidget(self.class_list)
        
        class_btn_layout = QHBoxLayout()
        class_btn_layout.setContentsMargins(0, 5, 0, 5)
        
        self.btn_add_class = QPushButton("添加")
        self.btn_add_class.setFixedWidth(55)
        self.btn_add_class.setFixedHeight(26)
        self.btn_add_class.setStyleSheet("font-size: 12px; padding: 0; margin: 0;")
        self.btn_add_class.clicked.connect(self._label_add_class)
        
        self.btn_rename_class = QPushButton("改名")
        self.btn_rename_class.setFixedWidth(55)
        self.btn_rename_class.setFixedHeight(26)
        self.btn_rename_class.setStyleSheet("font-size: 12px; padding: 0; margin: 0;")
        self.btn_rename_class.clicked.connect(self._label_rename_class)
        
        self.btn_delete_class = QPushButton("删除")
        self.btn_delete_class.setFixedWidth(55)
        self.btn_delete_class.setFixedHeight(26)
        self.btn_delete_class.setStyleSheet("font-size: 12px; padding: 0; margin: 0;")
        self.btn_delete_class.clicked.connect(self._label_delete_class)
        
        class_btn_layout.addWidget(self.btn_add_class)
        class_btn_layout.addSpacing(8)
        class_btn_layout.addWidget(self.btn_rename_class)
        class_btn_layout.addSpacing(8)
        class_btn_layout.addWidget(self.btn_delete_class)
        class_btn_layout.addStretch()
        label_manage_layout.addLayout(class_btn_layout)
        
        self.right_splitter.addWidget(label_manage_container)
        
        # --- 下部分：当前图片框列表 ---
        box_manage_container = QWidget()
        box_manage_layout = QVBoxLayout(box_manage_container)
        box_manage_layout.setContentsMargins(5, 5, 5, 5)
        
        box_manage_layout.addWidget(QLabel("当前图片框 (Delete 删除):"))
        self.box_list = QListWidget()
        self.box_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.box_list.customContextMenuRequested.connect(self._show_box_context_menu)
        self.box_list.itemClicked.connect(self._on_box_item_clicked)
        box_manage_layout.addWidget(self.box_list)
        
        self.right_splitter.addWidget(box_manage_container)
        
        # 设置右侧分割条初始比例
        self.right_splitter.setStretchFactor(0, 1) # 标签列表
        self.right_splitter.setStretchFactor(1, 1) # 框选列表
        
        right_main_layout.addWidget(self.right_splitter)
        self.label_splitter.addWidget(right_widget)
        
        # 设置初始比例
        self.label_splitter.setStretchFactor(0, 1) # 左侧
        self.label_splitter.setStretchFactor(1, 4) # 中间
        self.label_splitter.setStretchFactor(2, 1) # 右侧
        self.label_splitter.setSizes([200, 800, 250])

        # 标注状态
        self.current_dir = None
        self.current_img_path = None
        self.img_files = []
        self.classes = []  # 存储标签名列表

    def _label_open_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择数据集目录")
        if path:
            self.current_dir = path
            # 加载图片
            self.img_files = [f for f in os.listdir(path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            self.img_files.sort()
            self.file_list.clear()
            self.file_list.addItems(self.img_files)
            
            # 加载标签 classes.txt
            self._load_classes()
            
            self.label_info.setText(f"目录: {os.path.basename(path)} ({len(self.img_files)} 张)")
            if self.img_files:
                self.file_list.setCurrentRow(0)
                item = self.file_list.item(0)
                self.file_list.scrollToItem(item)
            self._on_file_selected(item)

    def _label_auto_annotate(self):
        """使用现有模型自动标注当前目录"""
        if not self.current_dir:
            QMessageBox.warning(self, "提示", "请先打开数据集目录")
            return
            
        # 1. 选择模型文件
        model_path, _ = QFileDialog.getOpenFileName(
            self, "选择用于自动标注的模型", "", "YOLO Models (*.pt)"
        )
        if not model_path:
            return
            
        # 2. 确认
        msg = "即将使用选定模型对当前目录下的所有图片进行自动标注。\n" \
              "注意：这将覆盖已有的同名 .txt 标签文件！\n\n" \
              "建议在执行前备份数据。\n" \
              "是否继续？"
        if QMessageBox.question(self, "确认自动标注", msg) != QMessageBox.Yes:
            return
            
        # 3. 启动线程
        self.btn_auto_label.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # 使用当前配置的置信度，或者默认 0.5
        conf = self.config.get("inference.conf_thres", 0.5)
        
        self.auto_label_thread = AutoAnnotationThread(model_path, self.current_dir, conf)
        self.auto_label_thread.progress.connect(self.progress_bar.setValue)
        self.auto_label_thread.finished.connect(self._on_auto_annotation_finished)
        self.auto_label_thread.start()

    def _on_auto_annotation_finished(self, success, message):
        self.btn_auto_label.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if success:
            QMessageBox.information(self, "完成", message)
            # 刷新当前显示的图片（如果有）
            if self.file_list.currentItem():
                self._on_file_selected(self.file_list.currentItem())
        else:
            QMessageBox.critical(self, "错误", message)

    def _label_auto_annotate(self):
        if not self.current_dir:
            QMessageBox.warning(self, "提示", "请先打开数据集目录")
            return
            
        # 选择模型
        model_path, _ = QFileDialog.getOpenFileName(self, "选择用于自动标注的模型", "", "YOLO Models (*.pt)")
        if not model_path:
            return
            
        # 确认
        msg = "即将使用选定模型对当前目录下的所有图片进行自动标注。\n注意：这将覆盖已有的同名 .txt 标签文件！\n建议在执行前备份数据。\n\n是否继续？"
        if QMessageBox.question(self, "确认自动标注", msg) != QMessageBox.Yes:
            return
            
        # 禁用按钮防止重复点击
        self.btn_auto_label.setEnabled(False)
        self.label_info.setText("正在自动标注中...")
        
        # 启动线程
        conf = self.config.get("inference.conf_thres", 0.5)
        self.auto_label_thread = AutoAnnotationThread(model_path, self.current_dir, conf)
        self.auto_label_thread.progress.connect(lambda p: self.label_info.setText(f"正在自动标注: {p}%"))
        self.auto_label_thread.finished.connect(self._on_auto_annotation_finished)
        self.auto_label_thread.start()

    def _on_auto_annotation_finished(self, success, message):
        self.btn_auto_label.setEnabled(True)
        if success:
            QMessageBox.information(self, "完成", message)
            self.label_info.setText("自动标注完成")
            # 刷新当前图片的标签
            if self.current_img_path:
                # 模拟重新选中当前文件以重载标签
                self._on_file_selected(self.file_list.currentItem())
        else:
            QMessageBox.critical(self, "错误", message)
            self.label_info.setText("自动标注失败")

    def _label_organize_dataset(self):
        """将标注好的数据整理为训练数据集（images/labels 结构）"""
        if not self.current_dir or not self.img_files:
            QMessageBox.warning(self, "提示", "请先打开包含图片的目录")
            return
            
        # 1. 寻找已标注的文件（存在同名 .txt 且内容不为空）
        valid_pairs = []
        for img_name in self.img_files:
            base_name = os.path.splitext(img_name)[0]
            label_name = base_name + ".txt"
            label_path = os.path.join(self.current_dir, label_name)
            
            if os.path.exists(label_path) and os.path.getsize(label_path) > 0:
                valid_pairs.append((img_name, label_name))
        
        if not valid_pairs:
            QMessageBox.warning(self, "提示", "未找到已标注的数据（请确保存在非空的 .txt 标签文件）")
            return
            
        # 2. 选择保存目录
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存训练数据集的根目录")
        if not save_dir:
            return
            
        # 防止用户选择当前正在标注的目录，导致自我复制冲突
        if os.path.abspath(save_dir) == os.path.abspath(self.current_dir):
            QMessageBox.critical(self, "错误", "保存目录不能是当前标注目录，请选择一个新的空目录。")
            return
            
        # 3. 确认操作
        msg = f"共找到 {len(valid_pairs)} 组已标注数据。\n将按照 95% 训练集、5% 验证集的比例整理到：\n{save_dir}\n\n是否继续？"
        if QMessageBox.question(self, "确认整理", msg) != QMessageBox.Yes:
            return
            
        try:
            # 4. 创建目录结构
            sub_dirs = [
                "images/train", "images/val",
                "labels/train", "labels/val"
            ]
            for sd in sub_dirs:
                os.makedirs(os.path.join(save_dir, sd), exist_ok=True)
            
            # 5. 随机分配并复制
            random.shuffle(valid_pairs)
            val_count = max(1, int(len(valid_pairs) * 0.05))
            val_data = valid_pairs[:val_count]
            train_data = valid_pairs[val_count:]
            
            # 辅助函数：复制文件
            def copy_files(data_list, subset):
                for img_name, lbl_name in data_list:
                    # 复制图片
                    shutil.copy2(
                        os.path.join(self.current_dir, img_name),
                        os.path.join(save_dir, "images", subset, img_name)
                    )
                    # 复制标签
                    shutil.copy2(
                        os.path.join(self.current_dir, lbl_name),
                        os.path.join(save_dir, "labels", subset, lbl_name)
                    )
            
            copy_files(train_data, "train")
            copy_files(val_data, "val")
            
            # 6. 复制 classes.txt 到 labels 目录
            classes_src = os.path.join(self.current_dir, "classes.txt")
            if os.path.exists(classes_src):
                # 仅存放在 labels 目录（符合 YOLO 标准结构）
                shutil.copy2(classes_src, os.path.join(save_dir, "labels", "classes.txt"))
            
            QMessageBox.information(self, "成功", f"数据集整理完成！\n训练集: {len(train_data)} 张\n验证集: {len(val_data)} 张")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"整理数据集时发生错误: {str(e)}")

    def _navigate_file(self, delta):
        row = self.file_list.currentRow()
        new_row = row + delta
        if 0 <= new_row < self.file_list.count():
            self.file_list.setCurrentRow(new_row)
            item = self.file_list.item(new_row)
            self.file_list.scrollToItem(item)
            self._on_file_selected(item)

    def _on_tab_changed(self, index):
        """当选项卡切换时"""
        if index == 2: # 切换到标注页
            # 强行设置焦点到主窗口，确保快捷键能立即响应
            self.setFocus()
            # 同时也让容易抢焦点的控件不要抢占焦点
            self.btn_toggle_draw.setFocusPolicy(Qt.NoFocus)
            self.btn_prev.setFocusPolicy(Qt.NoFocus)
            self.btn_next.setFocusPolicy(Qt.NoFocus)
            self.class_list.setFocusPolicy(Qt.NoFocus)
            self.box_list.setFocusPolicy(Qt.NoFocus)
            self.file_list.setFocusPolicy(Qt.NoFocus)

    def _toggle_draw_mode(self):
        self.canvas.draw_mode = self.btn_toggle_draw.isChecked()
        status = "开启" if self.canvas.draw_mode else "关闭"
        self.label_info.setText(f"标注模式: {status}")

    def _on_file_selected(self, item):
        if not item: return
        
        # 切换前先保存旧标签
        self._save_current_labels()
        
        filename = item.text()
        self.current_img_path = os.path.join(self.current_dir, filename)
        
        # 加载图片到画布
        self.canvas.set_image(self.current_img_path)
        
        # 加载已有标签
        label_filename = os.path.splitext(filename)[0] + ".txt"
        label_path = os.path.join(self.current_dir, label_filename)
        
        from PySide6.QtGui import QImageReader
        reader = QImageReader(self.current_img_path)
        img_size = reader.size()
        
        boxes = YOLOHelper.load_labels(label_path, img_size.width(), img_size.height())
        self.canvas.set_boxes(boxes)
        self._update_box_list_ui()

    def _load_classes(self):
        classes_path = os.path.join(self.current_dir, "classes.txt")
        self.classes = []
        if os.path.exists(classes_path):
            with open(classes_path, 'r', encoding='utf-8') as f:
                self.classes = [line.strip() for line in f if line.strip()]
        
        if not self.classes:
            self.classes = ["target"] # 默认一个
            self._save_classes()
            
        self._refresh_class_list_ui()

    def _refresh_class_list_ui(self):
        """刷新标签列表 UI，包含序号和颜色图标"""
        # 同步标签名称到画布，用于稳定颜色分配
        self.canvas.set_classes(self.classes)
        
        self.class_list.clear()
        for i, name in enumerate(self.classes):
            # 创建带颜色和序号的图标
            pixmap = QPixmap(20, 20)
            color = self.canvas.get_color(i)
            pixmap.fill(color)
            
            painter = QPainter(pixmap)
            painter.setPen(Qt.white if color.lightness() < 150 else Qt.black)
            font = painter.font()
            font.setBold(True)
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, str(i))
            painter.end()
            
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(QIcon(pixmap), name)
            self.class_list.addItem(item)
            
        if self.class_list.count() > 0:
            self.class_list.setCurrentRow(0)

    def _save_classes(self):
        if not self.current_dir: return
        classes_path = os.path.join(self.current_dir, "classes.txt")
        with open(classes_path, 'w', encoding='utf-8') as f:
            for cls in self.classes:
                f.write(f"{cls}\n")

    def _label_add_class(self):
        if not self.current_dir:
            QMessageBox.warning(self, "提示", "请先打开数据集目录")
            return
            
        text, ok = QInputDialog.getText(self, "添加标签", "请输入新标签名称:")
        if ok and text:
            text = text.strip()
            if not text: return
            if text not in self.classes:
                self.classes.append(text)
                self._save_classes()
                self._refresh_class_list_ui()
                self.class_list.setCurrentRow(len(self.classes) - 1)

    def _label_rename_class(self):
        idx = self.class_list.currentRow()
        if idx < 0: return
        
        old_name = self.classes[idx]
        text, ok = QInputDialog.getText(self, "重命名标签", f"将 '{old_name}' 重命名为:", QLineEdit.Normal, old_name)
        if ok and text:
            text = text.strip()
            if not text or text == old_name: return
            
            self.classes[idx] = text
            self._save_classes()
            self._refresh_class_list_ui()
            self.class_list.setCurrentRow(idx)
            self._update_box_list_ui()

    def _label_delete_class(self):
        idx = self.class_list.currentRow()
        if idx < 0: return
        
        class_name = self.classes[idx]
        reply = QMessageBox.warning(self, "确认删除", 
                                   f"确定要删除标签 '{class_name}' 吗？\n\n注意：这将从所有图片中删除该标签的所有标注，且无法撤销！",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # 1. 从列表移除
            self.classes.pop(idx)
            self._save_classes()
            self._refresh_class_list_ui()
            
            # 2. 全局清理所有 .txt 标签文件
            self._cleanup_labels_globally(idx)
            
            # 3. 刷新当前显示
            self._on_file_selected(self.file_list.currentItem())

    def _cleanup_labels_globally(self, deleted_idx):
        if not self.current_dir: return
        
        for filename in os.listdir(self.current_dir):
            if filename.lower().endswith(".txt") and filename != "classes.txt":
                file_path = os.path.join(self.current_dir, filename)
                updated_lines = []
                changed = False
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    for line in lines:
                        parts = line.strip().split()
                        if not parts: continue
                        
                        class_id = int(parts[0])
                        if class_id == deleted_idx:
                            # 删掉该行
                            changed = True
                            continue
                        elif class_id > deleted_idx:
                            # 索引前移
                            parts[0] = str(class_id - 1)
                            updated_lines.append(" ".join(parts) + "\n")
                            changed = True
                        else:
                            updated_lines.append(line)
                    
                    if changed:
                        if not updated_lines:
                            # 如果文件变空了，可以选择删除文件或写空
                            with open(file_path, 'w', encoding='utf-8') as f:
                                pass
                        else:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.writelines(updated_lines)
                                
                except Exception as e:
                    print(f"清理标签文件 {filename} 失败: {e}")

    def _on_class_changed(self, index):
        # 如果当前有选中的框，修改其类别
        if self.canvas.selected_idx >= 0 and index >= 0:
            self.canvas.boxes[self.canvas.selected_idx][4] = index
            self.canvas.update()
            self._update_box_list_ui()
            self._save_current_labels()

    def _on_box_selected_on_canvas(self, index):
        if index >= 0 and index < self.box_list.count():
            self.box_list.setCurrentRow(index)
            # 同时也选中对应的类别
            class_id = self.canvas.boxes[index][4]
            self.class_list.setCurrentRow(class_id)

    def _on_box_deleted_on_canvas(self, idx):
        if 0 <= idx < len(self.canvas.boxes):
            self.canvas.boxes.pop(idx)
            self.canvas.selected_idx = -1
            self.canvas.update()
            self._update_box_list_ui()
            self._save_current_labels()

    def _on_box_edit_requested(self, idx):
        if idx < 0 or idx >= len(self.canvas.boxes):
            return
            
        box = self.canvas.boxes[idx]
        current_class_id = box[4] if len(box) > 4 else 0
        current_class_name = self.classes[current_class_id] if current_class_id < len(self.classes) else f"ID:{current_class_id}"
        
        dialog = LabelSelectionDialog(current_class_name, self.classes, self)
        if dialog.exec_() == QDialog.Accepted:
            new_name = dialog.get_label()
            if not new_name:
                return
                
            if new_name not in self.classes:
                self.classes.append(new_name)
                self._save_classes()
                self._refresh_class_list_ui()
            
            new_id = self.classes.index(new_name)
            if len(box) > 4:
                self.canvas.boxes[idx][4] = new_id
            else:
                self.canvas.boxes[idx].append(new_id)
            
            self.canvas.update()
            self._update_box_list_ui()
            self._save_current_labels()
            # 同步右侧类列表选中状态
            self.class_list.setCurrentRow(new_id)

    def _on_box_item_clicked(self, item):
        index = self.box_list.row(item)
        if index >= 0:
            self.canvas.selected_idx = index
            self.canvas.update()
            # 同时也选中对应的类别
            if index < len(self.canvas.boxes):
                class_id = self.canvas.boxes[index][4]
                self.class_list.setCurrentRow(class_id)

    def _show_box_context_menu(self, pos):
        """显示框选列表的右键菜单"""
        item = self.box_list.itemAt(pos)
        if not item:
            return
            
        index = self.box_list.row(item)
        # 选中该项
        self.box_list.setCurrentRow(index)
        self.canvas.selected_idx = index
        self.canvas.update()
        
        menu = QMenu()
        edit_action = menu.addAction("修改标签")
        delete_action = menu.addAction("删除标注框")
        
        action = menu.exec_(self.box_list.mapToGlobal(pos))
        if action == edit_action:
            self._on_box_edit_requested(index)
        elif action == delete_action:
            self._shortcut_delete_box()

    def _on_box_added(self, pixel_box):
        if pixel_box is None:
            self._save_current_labels()
            return
            
        # 标注结束，直接使用当前选中的类别，不再弹出对话框
        # 用户需要修改标签时，双击标注框即可
        current_class_id = self.class_list.currentRow()
        if current_class_id < 0: current_class_id = 0
        
        new_box = pixel_box + [current_class_id]
        self.canvas.boxes.append(new_box)
        self.canvas.selected_idx = len(self.canvas.boxes) - 1
        self._update_box_list_ui()
        self._save_current_labels()
        self.box_list.setCurrentRow(self.canvas.selected_idx)
        self.canvas.update()

    def _update_box_list_ui(self):
        self.box_list.clear()
        for i, box in enumerate(self.canvas.boxes):
            if len(box) < 5:
                continue
            class_id = box[4]
            class_name = self.classes[class_id] if class_id < len(self.classes) else f"ID:{class_id}"
            self.box_list.addItem(f"[{class_name}] {box[0]},{box[1]} {box[2]}x{box[3]}")

    def _save_current_labels(self):
        if not self.current_img_path or not self.current_dir:
            return
            
        label_filename = os.path.splitext(os.path.basename(self.current_img_path))[0] + ".txt"
        label_path = os.path.join(self.current_dir, label_filename)
        
        from PySide6.QtGui import QPixmap
        px = QPixmap(self.current_img_path)
        
        # 即使 boxes 为空也执行保存（写入空文件），这样可以删除已有标签
        YOLOHelper.save_labels(label_path, self.canvas.boxes, px.width(), px.height())

    def _start_clicked(self):
        # 强制同步关键配置，防止 UI 状态与控制器不同步
        self.controller.trigger_mode = "manual"
        
        # 打印调试信息
        print(f"[UI] 启动系统: 模式=manual")
        
        show_debug = self.debug_check.isChecked()
        self.controller.start(show_debug=show_debug)
        self._update_status()

    def _stop_clicked(self):
        self.controller.stop()
        self._update_status()

    def _init_model_tab(self):
        layout = QVBoxLayout(self.model_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # 1. 模型选择部分
        model_group = QGroupBox("模型选择")
        model_layout = QVBoxLayout(model_group)
        
        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("当前模型:"))
        self.model_combo = QComboBox()
        self._refresh_model_list()
        self.model_combo.currentTextChanged.connect(self._on_model_selection_changed)
        sel_layout.addWidget(self.model_combo, 1)
        
        btn_browse_model = QPushButton("浏览...")
        btn_browse_model.clicked.connect(self._browse_model)
        sel_layout.addWidget(btn_browse_model)
        model_layout.addLayout(sel_layout)
        
        self.model_info_label = QLabel("提示: 基础模型 base.pt 用于推理和作为训练起点。")
        self.model_info_label.setStyleSheet("color: #888888; font-size: 11px;")
        model_layout.addWidget(self.model_info_label)
        
        layout.addWidget(model_group)
        
        # 1.5 模型优化部分 (TensorRT)
        opt_group = QGroupBox("模型优化 (TensorRT)")
        opt_layout = QVBoxLayout(opt_group)
        
        opt_params = QHBoxLayout()
        opt_params.addWidget(QLabel("导出尺寸 (imgsz):"))
        self.opt_imgsz_combo = QComboBox()
        self.opt_imgsz_combo.addItems(["320", "640", "960", "1280"])
        self.opt_imgsz_combo.setCurrentText("640")
        self.opt_imgsz_combo.setToolTip("建议与推理时的 FOV 匹配。640 是通用选择。")
        opt_params.addWidget(self.opt_imgsz_combo)
        
        opt_params.addSpacing(20)
        
        self.opt_half_check = QCheckBox("FP16 半精度")
        self.opt_half_check.setChecked(True)
        self.opt_half_check.setToolTip("显著提升速度，精度几乎无损。")
        opt_params.addWidget(self.opt_half_check)
        
        opt_params.addStretch()
        
        self.btn_export_trt = QPushButton("导出为 TensorRT 模型")
        self.btn_export_trt.setFixedHeight(32)
        self.btn_export_trt.setStyleSheet("background-color: #107c10; font-weight: bold;")
        self.btn_export_trt.clicked.connect(self._start_export)
        opt_params.addWidget(self.btn_export_trt)
        
        opt_layout.addLayout(opt_params)
        
        # 导出进度条
        self.opt_progress = QProgressBar()
        self.opt_progress.setVisible(False)
        self.opt_progress.setTextVisible(True)
        self.opt_progress.setAlignment(Qt.AlignCenter)
        self.opt_progress.setFormat("正在转换: %p%")
        self.opt_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #444444;
                text-align: center;
                color: white;
                height: 15px;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #107c10;
                border-radius: 2px;
            }
        """)
        opt_layout.addWidget(self.opt_progress)
        
        layout.addWidget(opt_group)

        # 2. 模型训练部分
        train_group = QGroupBox("模型训练 (YOLOv8)")
        train_layout = QVBoxLayout(train_group)
        
        # 显示当前使用的基础模型
        self.train_base_model_label = QLabel(f"当前训练基础权重: {os.path.basename(self.config.get('inference.model_path', 'base.pt'))}")
        self.train_base_model_label.setStyleSheet("color: #0078d4; font-weight: bold; margin-bottom: 5px;")
        train_layout.addWidget(self.train_base_model_label)
        
        # 数据集路径
        ds_layout = QHBoxLayout()
        ds_layout.addWidget(QLabel("数据集目录:"))
        self.train_ds_edit = QLineEdit()
        self.train_ds_edit.setPlaceholderText("选择包含 images/labels 的整理后的目录...")
        btn_browse_ds = QPushButton("选择")
        btn_browse_ds.clicked.connect(self._browse_train_dataset)
        ds_layout.addWidget(self.train_ds_edit)
        ds_layout.addWidget(btn_browse_ds)
        train_layout.addLayout(ds_layout)

        # 训练参数
        params_layout = QVBoxLayout()
        
        row1 = QHBoxLayout()
        # 轮次
        row1.addWidget(QLabel("训练轮次 (Epochs) (?)"))
        self.epochs_spin = QSpinBox()
        self.epochs_spin.setRange(1, 2000)
        self.epochs_spin.setValue(200)
        self.epochs_spin.setToolTip("整个数据集将被训练多少遍。通常 100-300 轮能获得较好效果。")
        row1.addWidget(self.epochs_spin)
        
        row1.addSpacing(20)
        
        # 工作线程
        row1.addWidget(QLabel("工作线程 (Workers) (?)"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(0, 16)
        self.workers_spin.setValue(2)
        self.workers_spin.setToolTip("加载数据的并行线程数。对于大多数 PC，设置为 2-4 即可。如果训练报错，尝试设为 0。")
        row1.addWidget(self.workers_spin)
        row1.addStretch()
        params_layout.addLayout(row1)

        row2 = QHBoxLayout()
        # Batch Size
        row2.addWidget(QLabel("批大小 (Batch) (?)"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(-1, 256)
        self.batch_spin.setValue(16)
        self.batch_spin.setSpecialValueText("自动 (-1)")
        self.batch_spin.setToolTip("每次模型参数更新所使用的图片数量。显存越大可设置越高。设为 -1 则由系统自动调整。")
        row2.addWidget(self.batch_spin)
        
        row2.addSpacing(20)
        
        # imgsz
        row2.addWidget(QLabel("训练分辨率 (imgsz) (?)"))
        self.imgsz_combo = QComboBox()
        self.imgsz_combo.addItems(["320", "640", "960", "1280", "1600", "1920"])
        self.imgsz_combo.setCurrentText("640")
        self.imgsz_combo.setToolTip("训练时图片缩放的大小。值越大精度越高，但训练越慢且越占显存。通常 640 是平衡点。")
        row2.addWidget(self.imgsz_combo)
        row2.addStretch()
        params_layout.addLayout(row2)

        row3 = QHBoxLayout()
        # Cache
        self.cache_check = QCheckBox("启用数据缓存 (Cache) (?)")
        self.cache_check.setToolTip("将处理后的图片预加载到内存。这能极大地提升训练速度（通常快 2-3 倍），但需要较大的内存空间。")
        self.cache_check.setChecked(True)
        row3.addWidget(self.cache_check)
        row3.addStretch()
        params_layout.addLayout(row3)
        
        train_layout.addLayout(params_layout)

        # 导出目录
        exp_layout = QHBoxLayout()
        exp_layout.addWidget(QLabel("导出结果目录:"))
        self.train_exp_edit = QLineEdit()
        self.train_exp_edit.setText(get_abs_path("train_results"))
        self.train_exp_edit.setPlaceholderText("选择训练结果导出目录...")
        btn_browse_exp = QPushButton("选择")
        btn_browse_exp.clicked.connect(self._browse_train_export)
        exp_layout.addWidget(self.train_exp_edit)
        exp_layout.addWidget(btn_browse_exp)
        train_layout.addLayout(exp_layout)

        # 训练日志
        train_layout.addWidget(QLabel("训练日志:"))
        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas;")
        train_layout.addWidget(self.train_log)

        # 训练进度
        self.train_progress = QProgressBar()
        self.train_progress.setVisible(False)
        self.train_progress.setTextVisible(True)
        self.train_progress.setAlignment(Qt.AlignCenter)
        self.train_progress.setFormat("训练进度: %p%")
        self.train_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #444444;
                text-align: center;
                color: white;
                height: 20px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #28a745;
                border-radius: 2px;
            }
        """)
        train_layout.addWidget(self.train_progress)

        # 训练按钮布局
        btn_train_layout = QHBoxLayout()
        
        # 开始训练按钮
        self.btn_start_train = QPushButton("开始训练")
        self.btn_start_train.setFixedHeight(40)
        self.btn_start_train.setStyleSheet("background-color: #0078d4; font-weight: bold;")
        self.btn_start_train.clicked.connect(self._start_training)
        btn_train_layout.addWidget(self.btn_start_train, 2)
        
        # 停止训练按钮
        self.btn_stop_train = QPushButton("停止训练")
        self.btn_stop_train.setFixedHeight(40)
        self.btn_stop_train.setEnabled(False) # 初始禁用
        self.btn_stop_train.setStyleSheet("background-color: #d83b01; font-weight: bold;")
        self.btn_stop_train.clicked.connect(self._stop_training)
        btn_train_layout.addWidget(self.btn_stop_train, 1)
        
        train_layout.addLayout(btn_train_layout)

        layout.addWidget(train_group)
        layout.addStretch()

    def _refresh_model_list(self):
        """刷新根目录下的模型列表"""
        self.model_combo.blockSignals(True) # 暂时阻塞信号，避免刷新时重复触发加载
        self.model_combo.clear()
        root = get_root_path()
        
        # 1. 添加内置模型 (项目根目录下的 .pt 和 .engine 文件，只显示文件名)
        models = [f for f in os.listdir(root) if f.endswith(".pt") or f.endswith(".engine")]
        if not models:
            models = ["base.pt"]
        # 排序：.pt 优先，然后按字母顺序
        models.sort(key=lambda x: (not x.endswith(".pt"), x))
        self.model_combo.addItems(models)
        
        # 2. 处理当前配置的显示
        current = self.config.get("inference.model_path", "base.pt")
        
        # 检查当前配置项是否已经在下拉列表中 (文件名或已存的绝对路径)
        idx = self.model_combo.findText(current)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            # 如果是外部路径且不在列表中，手动添加并显示全路径
            self.model_combo.addItem(current)
            self.model_combo.setCurrentText(current)
        
        self.model_combo.blockSignals(False)
        
        # 手动触发一次按钮状态更新
        self._update_export_button_state(current)
        
        # 同步更新训练部分的基础模型显示 (统一只显示简名)
        if hasattr(self, 'train_base_model_label'):
            self.train_base_model_label.setText(f"当前训练基础权重: {os.path.basename(current)}")

    def _update_export_button_state(self, model_path):
        """根据模型格式更新导出按钮状态"""
        if not hasattr(self, 'btn_export_trt'):
            return
            
        is_engine = model_path.endswith(".engine")
        self.btn_export_trt.setEnabled(not is_engine)
        if is_engine:
            self.btn_export_trt.setToolTip("当前已是 TensorRT 模型，无需优化")
        else:
            self.btn_export_trt.setToolTip("将当前模型转换为 TensorRT 格式以提升 FPS")

    def _on_model_selection_changed(self, model_name):
        if not model_name: return
        
        # 此时 model_name 是下拉框中显示的文本
        # 逻辑：
        # 1. 如果是绝对路径，说明是外部模型，配置保存全路径，加载也用全路径
        # 2. 如果是文件名，说明是内置模型，配置保存文件名，加载时拼接根目录
        
        if os.path.isabs(model_name):
            full_path = model_name
            save_val = model_name
        else:
            full_path = get_abs_path(model_name)
            save_val = model_name
            
        self.config.set("inference.model_path", save_val)
        
        # 更新按钮状态
        self._update_export_button_state(full_path)

        # 同步更新训练部分的基础模型显示
        if hasattr(self, 'train_base_model_label'):
            self.train_base_model_label.setText(f"当前训练基础权重: {os.path.basename(full_path)}")
            
        # 如果控制器已启动，尝试实时更新模型
        if self.controller:
            self.controller.model_path = full_path
            if self.controller.running:
                # 提示用户模型已实时加载
                self.status_text.setText(f"系统运行中 (模型已更新: {os.path.basename(full_path)})")

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模型文件", get_root_path(), "YOLO Models (*.pt *.engine)")
        if path:
            root = get_root_path()
            name = os.path.basename(path)
            
            # 确定显示和保存的文本
            # 如果选择的模型在项目根目录下，只显示文件名；否则显示全路径
            display_text = name if path.startswith(root) else path

            # 检查是否已经在 combo 中
            idx = self.model_combo.findText(display_text)
            if idx < 0:
                self.model_combo.addItem(display_text)
                idx = self.model_combo.count() - 1
            
            # 切换到该项 (会触发 _on_model_selection_changed)
            self.model_combo.setCurrentIndex(idx)

    def _start_export(self):
        """开始 TensorRT 导出"""
        model_path = self.config.get("inference.model_path", "base.pt")
        if not os.path.isabs(model_path):
            model_path = get_abs_path(model_path)
            
        if not os.path.exists(model_path):
            QMessageBox.warning(self, "错误", f"找不到模型文件: {model_path}")
            return
            
        if model_path.endswith(".engine"):
            QMessageBox.warning(self, "提示", "该模型已经是 TensorRT 格式 (.engine)，无需再次转换。")
            return

        # 确认对话框
        reply = QMessageBox.question(self, "导出确认", 
                                     f"确定要将 {os.path.basename(model_path)} 转换为 TensorRT 格式吗？\n\n"
                                     "注意：\n"
                                     "1. 导出过程需要 3-10 分钟，期间程序可能响应稍慢。\n"
                                     "2. 转换完成后将生成同名的 .engine 文件。\n"
                                     "3. 建议在导出期间不要进行其他大数据操作。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return

        # 界面状态更新
        self.btn_export_trt.setEnabled(False)
        self.opt_progress.setVisible(True)
        self.opt_progress.setRange(0, 0) # 忙碌状态
        self.train_log.appendPlainText(f"\n[{time.strftime('%H:%M:%S')}] --- 开始 TensorRT 转换任务 ---")

        # 启动线程
        imgsz = int(self.opt_imgsz_combo.currentText())
        half = self.opt_half_check.isChecked()
        
        self.export_thread = ExportTRTThread(model_path, imgsz, half)
        self.export_thread.log_signal.connect(self._on_export_log)
        self.export_thread.finished.connect(self._on_export_finished)
        self.export_thread.start()

    def _on_export_log(self, message):
        """处理导出日志"""
        self.train_log.appendPlainText(f"[Export] {message}")
        # 自动滚动到底部
        self.train_log.verticalScrollBar().setValue(self.train_log.verticalScrollBar().maximum())

    def _on_export_finished(self, success, message):
        """导出完成处理"""
        self.btn_export_trt.setEnabled(True)
        self.opt_progress.setVisible(False)
        self.opt_progress.setRange(0, 100)
        
        if success:
            QMessageBox.information(self, "导出成功", message)
            self.train_log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] 导出任务成功完成。")
            # 刷新模型列表，以便用户看到新的 .engine 文件（虽然推理引擎会自动检测，但刷新列表更直观）
            self._refresh_model_list()
        else:
            QMessageBox.critical(self, "导出失败", message)
            self.train_log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] 导出任务失败。")

    def _browse_train_dataset(self):
        path = QFileDialog.getExistingDirectory(self, "选择整理后的数据集目录")
        if path:
            self.train_ds_edit.setText(path)
            # 检查数据量
            img_train_dir = os.path.join(path, "images", "train")
            if os.path.exists(img_train_dir):
                count = len([f for f in os.listdir(img_train_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                if count < 50:
                    QMessageBox.warning(self, "警告", f"检测到训练集图片仅有 {count} 张。数据量少于 50 张，训练效果可能不理想，建议继续标注。")

    def _browse_train_export(self):
        path = QFileDialog.getExistingDirectory(self, "选择训练结果导出目录")
        if path:
            self.train_exp_edit.setText(path)

    def _stop_training(self):
        if not hasattr(self, 'training_thread') or not self.training_thread.isRunning():
            return
            
        reply = QMessageBox.question(self, "停止确认", "确定要停止当前正在进行的训练吗？\n停止后可能无法保存当前进度的权重。", 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.train_log.appendPlainText("\n[提示] 正在请求停止训练，请稍候...")
            self.btn_stop_train.setEnabled(False)
            self.training_thread.stop()

    def _start_training(self):
        dataset_path = self.train_ds_edit.text()
        if not dataset_path:
            QMessageBox.warning(self, "错误", "请先选择数据集目录。")
            return
            
        # 验证 data.yaml 是否存在，或者更新其中的路径
        yaml_path = os.path.join(dataset_path, "data.yaml")
        
        # 无论文件是否存在，我们都尝试读取并更新 path 字段，确保它指向用户当前选择的目录
        classes = []
        try:
            self.train_log.clear()
            self.train_log.appendPlainText("--- 正在检查训练配置 ---")
            
            classes_file = os.path.join(dataset_path, "classes.txt")
            if not os.path.exists(classes_file):
                classes_file = os.path.join(dataset_path, "labels", "classes.txt")
            
            if os.path.exists(classes_file):
                with open(classes_file, "r", encoding="utf-8") as f:
                    classes = [line.strip() for line in f if line.strip()]
            
            import yaml
            data_config = {}
            if os.path.exists(yaml_path):
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data_config = yaml.safe_load(f) or {}
                self.train_log.appendPlainText(f"检测到已存在的 data.yaml，正在同步路径...")
            else:
                self.train_log.appendPlainText(f"未检测到 data.yaml，正在根据 classes.txt 自动生成...")
            
            # 自动探测数据集结构
            def find_rel_path(base, target_sub_path):
                # 尝试几种常见的 YOLO 格式
                candidates = [
                    target_sub_path, # 如 images/train
                    target_sub_path.replace("/", "\\"), # Windows 风格
                    os.path.join("train", "images") if "train" in target_sub_path else os.path.join("val", "images"),
                ]
                for c in candidates:
                    if os.path.exists(os.path.join(base, c)):
                        return c.replace("\\", "/") # 统一使用正斜杠
                return None

            train_rel = find_rel_path(dataset_path, "images/train")
            val_rel = find_rel_path(dataset_path, "images/val")

            if not train_rel:
                # 兜底：如果没找到 images/train，检查根目录下是否有 images 文件夹
                if os.path.exists(os.path.join(dataset_path, "images")):
                    train_rel = "images"
                    val_rel = "images" # 这种情况下通常 val 也用同一个
                else:
                    QMessageBox.critical(self, "错误", "无法在数据集目录中找到图像文件夹 (images/train)。请确保数据集结构符合 YOLO 格式。")
                    return

            # 强制更新关键路径，确保在当前环境下可运行
            # 使用绝对路径以彻底绕过 Ultralytics settings.json 中的 datasets_dir 限制
            abs_dataset_path = dataset_path.replace("\\", "/")
            data_config['path'] = abs_dataset_path
            data_config['train'] = os.path.join(dataset_path, train_rel).replace("\\", "/")
            data_config['val'] = os.path.join(dataset_path, val_rel if val_rel else train_rel).replace("\\", "/")
            
            if classes:
                data_config['names'] = {i: name for i, name in enumerate(classes)}
            elif 'names' not in data_config:
                QMessageBox.critical(self, "错误", "在数据集目录中找不到 classes.txt，且 data.yaml 中也没有类别定义。无法训练。")
                return
            
            # 使用简单的文件写入，避免 yaml.dump 可能产生的格式问题（如 !!python/object）
            with open(yaml_path, "w", encoding="utf-8") as f:
                f.write(f"path: {data_config['path']}\n")
                f.write(f"train: {data_config['train']}\n")
                f.write(f"val: {data_config['val']}\n\n")
                f.write("names:\n")
                for i, name in data_config['names'].items():
                    f.write(f"  {i}: {name}\n")
            
            self.train_log.appendPlainText(f"配置完成: {yaml_path}")
            self.train_log.appendPlainText(f"训练路径 (Train): {data_config['train']}")
            self.train_log.appendPlainText(f"验证路径 (Val): {data_config['val']}")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"配置 data.yaml 失败: {e}")
            return

        # 检查轮次
        epochs = self.epochs_spin.value()
        if epochs < 50:
            QMessageBox.information(self, "建议", "推荐训练轮次为 150~200 轮，以获得较好的收敛效果。")

        # 准备训练
        raw_model_path = self.config.get("inference.model_path", "base.pt")
        # 确保基础模型是绝对路径
        model_path = get_abs_path(raw_model_path) if not os.path.isabs(raw_model_path) else raw_model_path
        
        workers = self.workers_spin.value()
        batch = self.batch_spin.value()
        imgsz = int(self.imgsz_combo.currentText())
        cache = self.cache_check.isChecked()
        project_dir = self.train_exp_edit.text()

        self.train_log.appendPlainText(f"\n--- 准备开始训练 ---")
        self.train_log.appendPlainText(f"基础模型: {model_path}")
        self.train_log.appendPlainText(f"配置文件: {yaml_path}")
        self.train_log.appendPlainText(f"训练轮次: {epochs}")
        self.train_log.appendPlainText(f"训练分辨率: {imgsz}")
        self.train_log.appendPlainText(f"工作线程: {workers}")
        self.train_log.appendPlainText(f"批大小 (Batch): {'自动' if batch == -1 else batch}")
        self.train_log.appendPlainText(f"数据缓存: {'开启' if cache else '关闭'}")
        self.train_log.appendPlainText(f"------------------\n")

        self.btn_start_train.setEnabled(False)
        self.btn_stop_train.setEnabled(True)
        self.train_progress.setVisible(True)
        # 使用 100 倍精度实现平滑进度显示 (从 epoch 级别细化到 batch 级别)
        self.train_progress.setRange(0, epochs * 100)
        self.train_progress.setValue(0)

        self.training_thread = TrainingThread(model_path, yaml_path, epochs, workers, project_dir, batch, cache, imgsz)
        self.training_thread.progress.connect(lambda msg: self.train_log.appendPlainText(msg))
        self.training_thread.epoch_progress.connect(lambda curr, total: self.train_progress.setValue(curr))
        self.training_thread.finished.connect(self._on_training_finished)
        self.training_thread.start()

    def _on_training_finished(self, success, message):
        self.btn_start_train.setEnabled(True)
        self.btn_stop_train.setEnabled(False)
        if success:
            self.train_progress.setValue(self.train_progress.maximum())
            QMessageBox.information(self, "训练完成", message)
            self.train_log.appendPlainText(f"\n[完成] {message}")
            # 训练完成后刷新模型列表，方便用户选择新训练的模型
            self._refresh_model_list()
        else:
            self.train_progress.setVisible(False)
            QMessageBox.critical(self, "训练失败", message)
            self.train_log.appendPlainText(f"\n[错误] {message}")

    def closeEvent(self, event):
        self.controller.stop()
        super().closeEvent(event)
