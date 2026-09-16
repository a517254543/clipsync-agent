"""路径适配 —— 兼容源码运行与 PyInstaller 打包（frozen）两种模式。

- frozen：资源（static / config.json）在 sys._MEIPASS 临时目录，用户数据（输出、配置）放在 exe 同级目录
- 源码：资源与数据都在项目目录
"""
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """代码与内置资源目录（只读）。"""
    if is_frozen():
        return Path(sys._MEIPASS) / "app"
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """可写目录：exe 同级（打包）或项目根目录（源码）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
