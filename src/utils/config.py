import json
import os

from .paths import get_abs_path

class ConfigManager:
    """
    配置管理类，负责保存和读取用户设置
    """
    DEFAULT_CONFIG = {
        "inference": {
            "model_path": "yolo26n.pt",
            "conf_thres": 0.4,
            "iou_thres": 0.45,
            "device": "cuda",
            "target_classes": [0]  # 0: person
        },
        "input": {
            "fov": 500,
            "auto_lock": True,
            "move_speed": "normal", # fast, normal, slow, custom
            "custom_speed_ms": 10,
            "custom_speed_random": 5,
            "human_curve": False,
            "offset_radius": 0,
            "mouse_sensitivity": 1.0,
            "move_key": "RButton",
            "post_action": "", # e.g., "LButton", "RButton", "Ctrl+A"
            "post_action_count": 1,
            "post_action_interval_ms": 10
        },
        "gui": {
            "theme": "dark",
            "show_debug": True
        }
    }
    
    @property
    def CONFIG_PATH(self):
        return get_abs_path("configs/config.json")

    def __init__(self):
        self.config = self.DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        """从文件加载配置"""
        if os.path.exists(self.CONFIG_PATH):
            try:
                with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    # 深度合并配置，确保默认值存在
                    self._deep_update(self.config, user_config)
            except Exception as e:
                print(f"[Config] 加载失败，使用默认值: {e}")
        else:
            self.save() # 创建默认配置文件

    def save(self):
        """保存当前配置到文件"""
        os.makedirs(os.path.dirname(self.CONFIG_PATH), exist_ok=True)
        try:
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] 保存失败: {e}")

    def _deep_update(self, base, update):
        for k, v in update.items():
            if isinstance(v, dict) and k in base:
                self._deep_update(base[k], v)
            else:
                base[k] = v

    def get(self, key_path: str, default=None):
        """通过路径获取配置，如 'inference.conf_thres'"""
        keys = key_path.split('.')
        val = self.config
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            return default

    def set(self, key_path: str, value):
        """通过路径设置配置"""
        keys = key_path.split('.')
        val = self.config
        for k in keys[:-1]:
            val = val.setdefault(k, {})
        val[keys[-1]] = value
        self.save()
