import sys
import os
import shutil
import random
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QGroupBox, QDoubleSpinBox, 
                             QCheckBox, QFrame, QSpacerItem, QSizePolicy,
                             QTabWidget, QFileDialog, QProgressBar, QComboBox,
                             QLineEdit, QMessageBox, QSpinBox, QListWidget, QInputDialog, QDialog,
                             QAbstractSpinBox, QTextEdit, QPlainTextEdit, QSplitter, QMenu)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QAction, QKeySequence, QShortcut, QPixmap, QPainter, QColor

from .styles import MAIN_STYLE
from .labeling_canvas import LabelingCanvas
from utils.config import ConfigManager
from utils.video_processor import VideoProcessor
from utils.yolo_helper import YOLOHelper

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

class MainWindow(QMainWindow):
    def __init__(self, controller, config: ConfigManager):
        super().__init__()
        self.controller = controller
        self.config = config
        
        self.setWindowTitle("AutoX - AI 控制中心")
        self.setMinimumSize(400, 500)
        self.setStyleSheet(MAIN_STYLE)
        
        self._init_ui()
        self._load_config_to_ui()
        
        # 状态更新定时器
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(500)

    def _init_ui(self):
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
        layout.setSpacing(12)

        # 标题栏
        title_label = QLabel("AutoX System")
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title_label)

        # 状态卡片
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet("background-color: #2d2d2d; border-radius: 8px; padding: 10px;")
        status_layout = QHBoxLayout(self.status_frame)
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: #d83b01; font-size: 18px;")
        self.status_text = QLabel("系统未启动")
        self.status_text.setStyleSheet("color: #ffffff; font-weight: bold;")
        status_layout.addWidget(self.status_indicator)
        status_layout.addWidget(self.status_text)
        status_layout.addStretch()
        layout.addWidget(self.status_frame)

        # 推理设置
        infer_group = QGroupBox("推理配置")
        infer_layout = QVBoxLayout(infer_group)
        
        conf_layout = QHBoxLayout()
        conf_layout.addWidget(QLabel("置信度阈值:"))
        self.conf_spin = QDoubleSpinBox()
        self.conf_spin.setRange(0.1, 0.9)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.valueChanged.connect(self._on_config_changed)
        conf_layout.addWidget(self.conf_spin)
        infer_layout.addLayout(conf_layout)
        
        self.debug_check = QCheckBox("显示实时预览窗口")
        self.debug_check.stateChanged.connect(self._on_config_changed)
        infer_layout.addWidget(self.debug_check)
        layout.addWidget(infer_group)

        # 行为设置
        input_group = QGroupBox("行为控制")
        input_layout = QVBoxLayout(input_group)
        
        smooth_layout = QHBoxLayout()
        smooth_layout.addWidget(QLabel("瞄准平滑度:"))
        self.smooth_spin = QDoubleSpinBox()
        self.smooth_spin.setRange(1.0, 10.0)
        self.smooth_spin.setSingleStep(0.5)
        self.smooth_spin.valueChanged.connect(self._on_config_changed)
        smooth_layout.addWidget(self.smooth_spin)
        input_layout.addLayout(smooth_layout)

        fov_layout = QHBoxLayout()
        fov_layout.addWidget(QLabel("锁定范围 (FOV):"))
        self.fov_spin = QDoubleSpinBox()
        self.fov_spin.setRange(50, 800)
        self.fov_spin.setSingleStep(10)
        self.fov_spin.valueChanged.connect(self._on_config_changed)
        fov_layout.addWidget(self.fov_spin)
        input_layout.addLayout(fov_layout)
        layout.addWidget(input_group)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # 控制按钮
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("启动系统")
        self.start_btn.setObjectName("start_btn")
        self.start_btn.setFixedHeight(45)
        self.start_btn.clicked.connect(self._start_clicked)
        
        self.stop_btn = QPushButton("停止")
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

    def _load_config_to_ui(self):
        self.conf_spin.setValue(self.config.get("inference.conf_thres"))
        self.debug_check.setChecked(self.config.get("gui.show_debug"))
        self.smooth_spin.setValue(self.config.get("input.sensitivity"))
        self.fov_spin.setValue(self.config.get("input.fov", 300))

    def _on_config_changed(self):
        # 更新配置对象并保存
        conf_val = self.conf_spin.value()
        debug_val = self.debug_check.isChecked()
        smooth_val = self.smooth_spin.value()
        fov_val = self.fov_spin.value()

        self.config.set("inference.conf_thres", conf_val)
        self.config.set("gui.show_debug", debug_val)
        self.config.set("input.sensitivity", smooth_val)
        self.config.set("input.fov", fov_val)
        
        # 同步到控制器
        if self.controller:
            self.controller.inference.conf_thres = conf_val
            self.controller.show_debug = debug_val
            # 将 UI 的平滑度 (1.0-10.0) 映射为秒数 (0.01s - 0.2s)
            self.controller.smooth_duration = smooth_val * 0.02 
            self.controller.smooth_move = smooth_val > 1.0
            self.controller.fov_size = fov_val

    def _update_status(self):
        if self.controller and self.controller.running:
            self.status_indicator.setStyleSheet("color: #107c10; font-size: 18px;")
            self.status_text.setText("系统运行中")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status_indicator.setStyleSheet("color: #d83b01; font-size: 18px;")
            self.status_text.setText("系统已停止")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

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
        show_debug = self.debug_check.isChecked()
        self.controller.start(show_debug=show_debug)
        self._update_status()

    def _stop_clicked(self):
        self.controller.stop()
        self._update_status()

    def closeEvent(self, event):
        self.controller.stop()
        super().closeEvent(event)
