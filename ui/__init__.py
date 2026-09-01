"""PySide6 GUI 入口。"""
import os
import sys


def app_dir()->str:
    """返回应用根目录（打包为 exe 时返回资源目录）。"""
    if getattr(sys, "frozen", False):  # PyInstaller
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def default_db_path() -> str:
    """默认词典数据库路径（可在 exe 同级放 oxford.db）。"""
    return os.path.join(app_dir(), "oxford.db")