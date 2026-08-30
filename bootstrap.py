import os
import sys

import _version

def is_vc_runtime_installed():
    r"""
    检测 VC++ 2015-2022 Redistributable 是否已安装
    通过检查注册表 HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64 是否存在来判断[reference:0][reference:1]
    返回 (是否已安装, 版本号或错误信息)
    """
    dll_path = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "vcruntime140.dll")
    if os.path.exists(dll_path):
        return True
    else:
        return False

print("loading...")

installed = is_vc_runtime_installed()

if installed:
    print(f"Visual C++ Redistributable detected")
else:
    print(f"Visual C++ Redistributable not installed")
    # print(f"{info}")
    print()
    print("Please install VC++ Redistributable from the link below:")
    print("请从以下链接下载并安装 VC++ Redistributable:")
    print("https://aka.ms/vs/17/release/vc_redist.x64.exe")
    print()
    print("Restart the program after vc_redist installed.")
    print("安装完成后请重新运行本程序。")
    print("Enter以退出...")
    # try:
    #     import webbrowser
    #     webbrowser.open("https://aka.ms/vs/17/release/vc_redist.x64.exe")
    # except Exception:
    #     pass
    input()
    sys.exit(1)
