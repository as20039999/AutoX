import sys
import os

# 将 src 目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from security.hardware import HardwareID
from security.license import LicenseManager

def test_security():
    print("--- 开始 Security 模块验证 ---")
    
    # 1. 硬件信息提取
    print("1. 正在获取硬件指纹...")
    mid = HardwareID.get_machine_id()
    print(f"   Machine ID: {mid}")
    
    # 2. 模拟授权生成 (离线算号)
    print("2. 模拟生成 30 天授权码...")
    license_key = LicenseManager.generate_key(mid, days=30)
    print(f"   Generated Key: {license_key}")
    
    # 3. 模拟保存授权
    print("3. 正在保存授权文件...")
    LicenseManager.save_license(license_key)
    
    # 4. 验证授权
    print("4. 正在验证本地授权...")
    if LicenseManager.verify_local_license():
        print("   [SUCCESS] 授权验证通过！")
    else:
        print("   [FAILED] 授权验证失败！")
        
    # 5. 测试篡改验证 (模拟非法授权)
    print("5. 测试非法授权 (机器码不匹配)...")
    fake_mid = "FAKE-MACHINE-ID-123456"
    fake_key = LicenseManager.generate_key(fake_mid, days=30)
    LicenseManager.save_license(fake_key)
    if not LicenseManager.verify_local_license():
        print("   [SUCCESS] 成功拦截非法授权！")
    else:
        print("   [FAILED] 未能识别非法授权！")
        
    print("--- Security 模块验证完成 ---")

if __name__ == "__main__":
    test_security()
