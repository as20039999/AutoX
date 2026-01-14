import win32api
import win32con

# 键名到 VK Code 的映射
KEY_MAP = {
    'LButton': 0x01, 'RButton': 0x02, 'Cancel': 0x03, 'MButton': 0x04, 
    'XButton1': 0x05, 'XButton2': 0x06,
    'Backspace': 0x08, 'Tab': 0x09, 'Clear': 0x0C, 'Enter': 0x0D,
    'Shift': 0x10, 'Ctrl': 0x11, 'Alt': 0x12, 'Pause': 0x13, 'CapsLock': 0x14,
    'Esc': 0x1B, 'Space': 0x20, 'PageUp': 0x21, 'PageDown': 0x22,
    'End': 0x23, 'Home': 0x24, 'Left': 0x25, 'Up': 0x26, 'Right': 0x27, 'Down': 0x28,
    'Select': 0x29, 'Print': 0x2A, 'Execute': 0x2B, 'PrintScreen': 0x2C, 'Insert': 0x2D, 'Delete': 0x2E,
    'Help': 0x2F,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45, 'F': 0x46, 'G': 0x47, 'H': 0x48, 'I': 0x49,
    'J': 0x4A, 'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E, 'O': 0x4F, 'P': 0x50, 'Q': 0x51, 'R': 0x52,
    'S': 0x53, 'T': 0x54, 'U': 0x55, 'V': 0x56, 'W': 0x57, 'X': 0x58, 'Y': 0x59, 'Z': 0x5A,
    'LWin': 0x5B, 'RWin': 0x5C, 'Apps': 0x5D, 'Sleep': 0x5F,
    'NumPad0': 0x60, 'NumPad1': 0x61, 'NumPad2': 0x62, 'NumPad3': 0x63, 'NumPad4': 0x64,
    'NumPad5': 0x65, 'NumPad6': 0x66, 'NumPad7': 0x67, 'NumPad8': 0x68, 'NumPad9': 0x69,
    'Multiply': 0x6A, 'Add': 0x6B, 'Separator': 0x6C, 'Subtract': 0x6D, 'Decimal': 0x6E, 'Divide': 0x6F,
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75, 'F7': 0x76, 'F8': 0x77,
    'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    'NumLock': 0x90, 'ScrollLock': 0x91,
    'LShift': 0xA0, 'RShift': 0xA1, 'LCtrl': 0xA2, 'RCtrl': 0xA3, 'LAlt': 0xA4, 'RAlt': 0xA5,
    ';': 0xBA, '=': 0xBB, ',': 0xBC, '-': 0xBD, '.': 0xBE, '/': 0xBF, '`': 0xC0,
    '[': 0xDB, '\\': 0xDC, ']': 0xDD, "'": 0xDE
}

# VK Code 到键名的反向映射 (用于显示)
VK_MAP = {v: k for k, v in KEY_MAP.items()}

def is_key_pressed(vk_code):
    """检测单个键是否被按下"""
    return win32api.GetAsyncKeyState(vk_code) < 0

def is_hotkey_pressed(hotkey_str):
    """
    检测组合键是否被按下
    :param hotkey_str: 类似 "Ctrl+Alt+A" 或 "Shift" 的字符串
    """
    if not hotkey_str:
        return False
        
    keys = hotkey_str.split('+')
    for key in keys:
        key = key.strip()
        vk = KEY_MAP.get(key)
        if vk is None:
            # 尝试直接查找 (例如可能是数字)
            continue
        
        if not is_key_pressed(vk):
            return False
            
    return True

def get_pressed_keys():
    """获取当前所有被按下的键名列表"""
    pressed = []
    for name, vk in KEY_MAP.items():
        # 过滤掉通用的 Ctrl/Shift/Alt，只保留左右区分的，或者只保留通用的
        # 这里我们只检测通用的修饰键，避免 LShift 和 Shift 同时出现
        if name in ['LShift', 'RShift', 'LCtrl', 'RCtrl', 'LAlt', 'RAlt']:
            continue
            
        if is_key_pressed(vk):
            pressed.append(name)
            
    # 特殊处理修饰键，如果需要更友好的显示
    # (可选优化：合并 LCtrl/RCtrl 为 Ctrl)
    return pressed

def get_pressed_hotkey_str():
    """
    获取当前按下的组合键字符串
    优先级：Ctrl > Alt > Shift > 其他
    """
    pressed = []
    
    # 强制检查修饰键 (因为上面的循环可能跳过了 L/R)
    if is_key_pressed(win32con.VK_CONTROL): pressed.append("Ctrl")
    if is_key_pressed(win32con.VK_MENU): pressed.append("Alt")
    if is_key_pressed(win32con.VK_SHIFT): pressed.append("Shift")
    
    # 检查其他键
    for name, vk in KEY_MAP.items():
        if name in ['Shift', 'Ctrl', 'Alt', 'LShift', 'RShift', 'LCtrl', 'RCtrl', 'LAlt', 'RAlt']:
            continue
        if is_key_pressed(vk):
            pressed.append(name)
            
    if not pressed:
        return None
        
    return "+".join(pressed)
