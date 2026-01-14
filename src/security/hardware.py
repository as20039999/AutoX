import subprocess
import hashlib
import platform

class HardwareID:
    """
    硬件指纹提取类，用于生成机器唯一的标识符 (HWID)
    """

    @staticmethod
    def _run_powershell(command: str) -> str:
        """执行 PowerShell 命令并返回结果"""
        try:
            full_cmd = f"powershell -NoProfile -Command \"{command}\""
            output = subprocess.check_output(full_cmd, shell=True).decode().strip()
            return output
        except Exception:
            return ""

    @staticmethod
    def get_cpu_id() -> str:
        """获取 CPU 序列号"""
        # 使用 Get-CimInstance 替代 wmic
        res = HardwareID._run_powershell("(Get-CimInstance Win32_Processor).ProcessorId")
        return res if res else "UNKNOWN_CPU"

    @staticmethod
    def get_disk_serial() -> str:
        """获取物理硬盘序列号 (取第一块)"""
        # 使用 Get-CimInstance 替代 wmic
        res = HardwareID._run_powershell("(Get-CimInstance Win32_DiskDrive | Select-Object -First 1).SerialNumber")
        return res.strip() if res else "UNKNOWN_DISK"

    @staticmethod
    def get_baseboard_serial() -> str:
        """获取主板序列号"""
        # 使用 Get-CimInstance 替代 wmic
        res = HardwareID._run_powershell("(Get-CimInstance Win32_BaseBoard).SerialNumber")
        return res if res else "UNKNOWN_BOARD"

    @classmethod
    def get_machine_id(cls) -> str:
        """
        组合多种硬件信息生成唯一的机器 ID
        使用 SHA256 混淆
        """
        raw_id = f"{cls.get_cpu_id()}-{cls.get_disk_serial()}-{cls.get_baseboard_serial()}-{platform.node()}"
        return hashlib.sha256(raw_id.encode()).hexdigest().upper()

if __name__ == "__main__":
    print(f"CPU ID: {HardwareID.get_cpu_id()}")
    print(f"Disk Serial: {HardwareID.get_disk_serial()}")
    print(f"BaseBoard Serial: {HardwareID.get_baseboard_serial()}")
    print(f"Generated Machine ID: {HardwareID.get_machine_id()}")
