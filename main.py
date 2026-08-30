# -*- coding: utf-8 -*-
"""
orbitcalculator 启动器:

    python main.py [--host 127.0.0.1] [--port 8765] [--jobs 8] [--no-browser]

启动 Flask 服务, 自动打开用户默认浏览器,
浏览器中完成"配置 -> 计算 -> 可视化"闭环 (无需写任何 Python 脚本)。

单实例 (默认):
    固定端口 bind 即权威 —— bind 失败说明已有实例在运行,
    直接打开已有实例的前端并退出 (不启动第二个服务)。

系统配置 (SysConfig):
    启动前先读取 orbitcalculator.sys.json (程序目录/工作目录旁, 回退 %APPDATA%),
    命令行参数优先于文件; 文件内可设 host=0.0.0.0 (局域网, 附安全警告) 等。

端口策略:
    --port 0  -> 随机选空闲端口 (禁用单实例锁语义)
    其他      -> 固定该端口; 被占用时若 single_instance 则直接打开已有实例
"""
from _version import __version__

import bootstrap

import argparse
import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from orbcalc.sysconfig import SysConfig, load_sysconfig, save_sysconfig

LOCK_FILE = "orbitcalculator.lock.json"


def _lock_path() -> Path:
    """锁文件路径: 程序目录旁优先, 回退 %APPDATA%/orbitcalculator/."""
    base = Path(os.path.dirname(os.path.abspath(sys.argv[0] or ".")))
    p = base / LOCK_FILE
    if os.access(str(base), os.W_OK):
        return p
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "orbitcalculator" / LOCK_FILE
    return p


def find_free_port(start: int, tries: int = 11) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"端口 {start}..{start + tries - 1} 全部被占用")


def _write_lock(host: str, port: int) -> Path:
    """写信息性锁文件 (不参与单实例判定, 仅调试/查端口用)."""
    lock = _lock_path()
    try:
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        lock.write_text(json.dumps({
            "host": host, "port": port,
            "url": f"http://127.0.0.1:{port}/",
            "pid": os.getpid(), "started": time.time(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return lock


def main():
    # PyInstaller 冻结版子进程模式: pasta.exe --cli --config ... --outdir ...
    if len(sys.argv) >= 2 and sys.argv[1] == "--cli":
        # 剥掉 --cli 标记再交给 run_cli (它的 argparse 不认 --cli)
        sys.argv = [sys.argv[0]] + (sys.argv[2:] if len(sys.argv) > 2 else [])
        from orbcalc.run_cli import main as cli_main
        sys.exit(cli_main())

    ap = argparse.ArgumentParser(description="orbitcalculator Web 启动器")
    ap.add_argument("--host", default=None, help="监听地址 (默认取系统配置 127.0.0.1; 0.0.0.0=局域网, 仅限安全内网)")
    ap.add_argument("--port", type=int, default=None, help="端口 (默认取系统配置 8765; 0=随机空闲端口, 禁用单实例)")
    ap.add_argument("--jobs", type=int, default=None, help="默认并行进程数 (可被任务配置覆盖; 缺省用配置值)")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    # 系统配置 (文件) -> 命令行覆盖
    syscfg = load_sysconfig()
    if args.host:
        syscfg.host = args.host
    if args.port is not None:
        syscfg.port = args.port
    syscfg.validate()

    host, port = syscfg.host, syscfg.port

    # 0.0.0.0 安全警告: 仅限安全内网, 无鉴权
    if syscfg.is_lan and syscfg.show_lan_warning:
        print("[warn] 监听 0.0.0.0: 局域网内任何设备可访问, 且本工具无鉴权 — 仅限安全内网使用!")

    import pykep
    import pygmo
    print(f"pykep {pykep.__version__}  pygmo {pygmo.__version__}")

    from webapp.app import app
    if args.jobs:
        app.config["DEFAULT_JOBS"] = args.jobs
    app.config["SYS"] = syscfg

    # ---- 端口策略 ----
    if syscfg.port == 0:
        # 随机空闲端口 (无单实例语义)
        port = find_free_port(8765)
        print(f"[main] 随机端口: {port}")
    else:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
        except OSError:
            if syscfg.single_instance:
                # 已有实例在运行: 直接打开其前端并退出 (锁文件仅辅助)
                url = f"http://127.0.0.1:{port}/"
                try:
                    lock = _lock_path()
                    if lock.exists():
                        lock_json = json.loads(lock.read_text(encoding="utf-8"))
                        url = lock_json.get("url", url)
                except Exception:
                    pass
                print(f"[main] 端口 {port} 已被实例占用, 打开已有实例: {url}")
                webbrowser.open(url)
                sys.exit(0)
            raise SystemExit(f"[main] 端口 {port} 绑定失败且未启用单实例, 请换端口 (--port)")

    url = f"http://127.0.0.1:{port}/"
    print(f"[main] orbitcalculator Web: {url}")
    _write_lock(host, port)

    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port,
                               threaded=True, use_reloader=False),
        daemon=True,
    )
    thread.start()

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[main] stopped")


if __name__ == "__main__":
    # PyInstaller 冻结版必需: multiprocessing 池的 spawn 子进程以 pasta.exe 入口重新执行,
    # 必须由 freeze_support() 拦截并转入 spawn_main, 否则 worker 会进主流程崩溃 (BrokenProcessPool)。
    multiprocessing.freeze_support()
    main()