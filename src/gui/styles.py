# 现代暗黑风格 QSS
MAIN_STYLE = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #ffffff;
}

QWidget {
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
    color: #dcdcdc;
}

/* 选项卡样式 */
QTabWidget::pane {
    border: 1px solid #333333;
    background-color: #1e1e1e;
    top: -1px;
}

QTabBar::tab {
    background-color: #2d2d2d;
    color: #aaaaaa;
    padding: 10px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #1e1e1e;
    color: #0078d4;
    border-bottom: 2px solid #0078d4;
}

QTabBar::tab:hover {
    background-color: #333333;
}

/* 进度条样式 */
QProgressBar {
    border: 1px solid #333333;
    border-radius: 4px;
    background-color: #2d2d2d;
    text-align: center;
    color: #ffffff;
}

QProgressBar::chunk {
    background-color: #0078d4;
    width: 10px;
}

QGroupBox {
    border: 1px solid #333333;
    border-radius: 8px;
    margin-top: 15px;
    padding-top: 10px;
    font-weight: bold;
    color: #0078d4;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}

QLabel {
    color: #ffffff;
}

QPushButton {
    background-color: #333333;
    border: none;
    border-radius: 5px;
    padding: 8px 15px;
    color: #ffffff;
    min-width: 80px;
}

QPushButton:hover {
    background-color: #444444;
}

QPushButton#start_btn {
    background-color: #0078d4;
    font-weight: bold;
}

QPushButton#start_btn:hover {
    background-color: #0086f0;
}

QPushButton#stop_btn {
    background-color: #d83b01;
    font-weight: bold;
}

QPushButton#stop_btn:hover {
    background-color: #ea4a1f;
}

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background-color: #2d2d2d;
    border: 1px solid #444444;
    border-radius: 4px;
    padding: 4px;
    color: #ffffff;
    min-height: 32px;
}

QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #ffffff;
    selection-background-color: #0078d4;
    outline: none;
    border: 1px solid #444444;
}

QLineEdit:focus, QDoubleSpinBox:focus {
    border: 1px solid #0078d4;
}

QSlider::groove:horizontal {
    border: 1px solid #444444;
    height: 4px;
    background: #333333;
    margin: 2px 0;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #0078d4;
    border: 1px solid #0078d4;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QCheckBox {
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
}

/* 列表样式 */
QListWidget {
    background-color: #252526;
    border: 1px solid #333333;
    border-radius: 4px;
    outline: none;
}

QListWidget::item {
    padding: 5px;
    border-radius: 2px;
}

QListWidget::item:selected {
    background-color: #37373d;
    color: #0078d4;
    font-weight: bold;
}

QListWidget::item:hover {
    background-color: #2a2d2e;
}

/* 分割条样式 */
QSplitter::handle {
    background-color: #333333;
    margin: 2px;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

QSplitter::handle:hover {
    background-color: #0078d4;
}
"""
