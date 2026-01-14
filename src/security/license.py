import hashlib
import json
import os
from datetime import datetime, timedelta
from .hardware import HardwareID

class LicenseManager:
    """
    授权管理类 (基础版本)
    实现基于机器码的本地授权校验
    """
    
    SECRET_SALT = "AutoX_Secure_Salt_2026" # 混淆盐值
    LICENSE_FILE = "license.dat"

    @classmethod
    def generate_key(cls, machine_id: str, days: int = 30) -> str:
        """
        生成授权码 (模拟算号器逻辑)
        格式: SHA256(machine_id + salt + expiry_date)
        """
        expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        raw_str = f"{machine_id}|{expiry_date}|{cls.SECRET_SALT}"
        signature = hashlib.sha256(raw_str.encode()).hexdigest()
        
        # 返回组合后的授权数据
        return f"{expiry_date}.{signature}"

    @classmethod
    def verify_local_license(cls) -> bool:
        """
        验证本地授权文件
        """
        if not os.path.exists(cls.LICENSE_FILE):
            print("[Security] 未找到授权文件")
            return False
            
        try:
            with open(cls.LICENSE_FILE, "r") as f:
                license_data = f.read().strip()
                
            expiry_date_str, signature = license_data.split('.')
            
            # 1. 检查是否过期
            expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d")
            if datetime.now() > expiry_date:
                print(f"[Security] 授权已过期 (到期时间: {expiry_date_str})")
                return False
                
            # 2. 校验签名是否匹配当前机器
            machine_id = HardwareID.get_machine_id()
            raw_str = f"{machine_id}|{expiry_date_str}|{cls.SECRET_SALT}"
            expected_signature = hashlib.sha256(raw_str.encode()).hexdigest()
            
            if signature == expected_signature:
                print(f"[Security] 授权验证通过 (到期时间: {expiry_date_str})")
                return True
            else:
                print("[Security] 授权码与当前机器不匹配")
                return False
                
        except Exception as e:
            print(f"[Security] 授权文件损坏或格式错误: {e}")
            return False

    @classmethod
    def save_license(cls, key: str):
        """保存授权码到本地"""
        with open(cls.LICENSE_FILE, "w") as f:
            f.write(key)
        print(f"[Security] 授权码已保存至 {cls.LICENSE_FILE}")

if __name__ == "__main__":
    # 模拟流程
    mid = HardwareID.get_machine_id()
    print(f"当前机器码: {mid}")
    
    # 生成一个 7 天的测试 Key
    test_key = LicenseManager.generate_key(mid, days=7)
    print(f"生成的测试 Key: {test_key}")
    
    # 保存并验证
    LicenseManager.save_license(test_key)
    LicenseManager.verify_local_license()
