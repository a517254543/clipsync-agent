"""一拍即合 ClipSync Agent —— 桌面启动器

双击 exe 后：启动本地服务 → 自动打开浏览器 → 控制台显示运行状态。
此窗口是服务进程，最小化即可，关闭即退出程序。
"""
import os
import socket
import sys
import threading
import time
import webbrowser

BANNER = r"""
====================================================
   一拍即合 ClipSync Agent  v0.1
   短视频脚本智造与多平台分发智能体
   OPC轻创赛道 · 短视频内容生产与新媒体营销场景
====================================================
"""


def pick_port(start: int = 8521, tries: int = 20) -> int:
    """找一个可用端口，避免端口占用导致启动失败。"""
    for i in range(tries):
        port = start + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def open_browser(url: str, delay: float = 2.0):
    def _run():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def setup_console():
    """Windows 控制台默认 GBK，输出中文符号会抛 UnicodeEncodeError。
    先切到 UTF-8 代码页，再把 stdout/stderr 重配为 utf-8。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    setup_console()
    print(BANNER)
    port = int(os.environ.get("CLIPSYNC_PORT", pick_port()))
    url = f"http://127.0.0.1:{port}"

    print(f"  服务地址：{url}")
    print("  正在启动，浏览器将自动打开…")
    print("  ⚠ 请勿关闭本窗口，关闭即退出程序")
    print("=" * 52 + "\n")

    # 显式导入（便于 PyInstaller 静态分析时收集 app 包及其子模块）
    from app.main import app  # noqa: F401
    import uvicorn
    open_browser(url)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port,
                    log_level="warning", access_log=False)
    except Exception as e:
        print(f"\n[启动失败] {e}")
        print("请检查端口是否被占用，或以管理员身份重试。")
        if not getattr(sys, "frozen", False):
            raise
        try:
            input("\n按回车键退出…")
        except Exception:
            pass


if __name__ == "__main__":
    main()
