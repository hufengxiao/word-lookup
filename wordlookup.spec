# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：WordLookup.exe（通用查词工具）
# 用法：pyinstaller wordlookup.spec  （或直接运行 build_exe.bat）
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

# 收集 python-lzo 的 C 扩展（Windows 上解压 MDX 必需）
lzo_binaries, lzo_datas, lzo_hidden = collect_all('lzo', on_error='ignore')

# 词典包全部模块（含子进程构建用到的 indexer/mdx_parser/lzo/ripemd128/searcher）
dict_submodules = collect_submodules('dictionary')
# UI 包全部模块（含 v0.8.4 新自绘文件选择器 ui/mdx_picker）
ui_submodules = collect_submodules('ui')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=lzo_binaries,
    datas=[('assets', 'assets'),      # 图标等静态资源, 供托盘/前台使用; 不含词典 db
           ('version.txt', '.')],     # 版本号(单一来源, 由 CI 注入, get_version() 读取)
    hiddenimports=['dictionary.indexer', 'dictionary.mdx_parser',
                   'dictionary.searcher', 'dictionary.lzo',
                   'dictionary.ripemd128', 'multiprocessing',
                   'ui.mdx_picker'] + dict_submodules + ui_submodules + lzo_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WordLookup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # UPX 压缩易触发杀软误报 + 增大解压折中; 关闭求稳
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # Windows 下不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/WordLookup.ico',
)