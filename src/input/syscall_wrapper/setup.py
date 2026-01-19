from setuptools import setup, Extension
import os

# 配置汇编器 (MASM)
# 注意：在 Windows 上通常需要通过 VS Command Prompt 运行
# 或者在 setup.py 中指定编译器选项

module = Extension(
    'syscall_input_lib',
    sources=['syscall_module.c'],
    extra_objects=['syscall_stubs.obj'], # 直接链接编译好的对象文件
    extra_compile_args=['/Ox'],
)

# 告诉 setuptools 如何处理 .asm 文件
# 这里简单起见，假设用户已经将 .asm 预编译为 .obj
# 或者使用自定义 build 逻辑。更简单的方法是使用 Nuitka 直接集成。

setup(
    name='syscall_input_lib',
    version='1.0',
    description='Syscall wrapper for AutoX',
    ext_modules=[module],
)
