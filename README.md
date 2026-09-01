# Oxford Lookup · 轻量查词工具

[![Build](https://github.com/hufengxiao/word-lookup/actions/workflows/build.yml/badge.svg)](https://github.com/hufengxiao/word-lookup/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/hufengxiao/word-lookup?sort=semver&color=blue)](https://github.com/hufengxiao/word-lookup/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个像 macOS **Spotlight** 一样即按即查的悬浮查词工具，专为 Windows 设计。

按 **Ctrl + Shift + M** 唤起搜索框 → 输入英文单词即时联想 → **回车** 打开词条详情。窗口保持置顶，失焦自动变「近乎透明」，鼠标移入即恢复——不打扰你的其它工作。

## ✨ 功能

| 特性 | 说明 |
|------|------|
| 🖥 全局热键 | `Ctrl+Shift+M` 唤起 / 隐藏（Windows） |
| 🔍 Spotlight 交互 | 输入即联想，`↑/↓` 选择，`Enter` 进详情，`Esc` 关闭 |
| 📖 词典 | 读取 **MDX 词典**（默认内置牛津高阶第 10 版英汉双解 V13.2），原生支持 LZO/zlib 压缩 |
| ⚡ 性能 | 30 万+ 词条，查询最快 **<1ms**（SQLite B-tree 前缀索引） |
| 🪟 智能透明度 | 失焦→近乎透明；鼠标移入→恢复；窗口可拖动 |
| 📦 轻量 | 运行时只需 PySide6，词典正文转 SQLite 后即查即读，无需再解压 MDX |

## 📂 项目结构

```
oxford-lookup/
├── main.py                    # 入口（热键 + 搜索窗）
├── dictionary/
│   ├── mdx_parser.py          # MDX 解析器（含 LZO/zlib 解压）
│   ├── lzo.py                 # LZO 跨平台解压（ctypes / python-lzo）
│   ├── ripemd128.py           # 词典解密哈希
│   ├── indexer.py             # .mdx → oxford.db 一键构建
│   ├── searcher.py            # Spotlight 式前缀搜索 + 精确查词
│   └── summary.py             # 联想结果的中文释义预览提取
├── ui/
│   ├── search_window.py       # 悬浮搜索窗（透明度/拖动/联想/详情内嵌）
│   ├── detail_window.py       # 词条详情窗（HTML 渲染）
│   └── dict_render.py         # 牛津 HTML → 深色排版 HTML 语义转换
├── hotkey/
│   └── win_hotkey.py          # Windows 全局热键（RegisterHotKey）
├── tests/
│   └── test_dict_render.py    # dict_render / 例句提取的单元测试
├── smoke_test.py              # 端到端冒烟（搜索/详情/透明度/拖动）
├── smoke_db.py               # 生成 CI 冒烟用的最小词典库
├── requirements.txt
├── pyproject.toml             # 项目元数据 + ruff / pytest 配置
├── build.md                   # Windows 打包为 exe 的说明
├── build_exe.bat *            # 一键打包（Windows）
└── wordlookup.spec            # PyInstaller 打包配置
```

## 🚀 快速开始

### 1. 构建词典数据库（一次性）

需先把 `.mdx` 词典转成轻量 SQLite（`oxford.db`）：

```bash
# 需要 readmdict + python-lzo + lxml（Windows 上均有 wheel）
pip install readmdict python-lzo lxml

# 转换（在本项目根目录）
python -m dictionary.indexer "牛津高阶第10版英汉双解V132.mdx" oxford.db
```

> 没有 python-lzo 也能构建：本项目 `dictionary/lzo.py` 会自动回退到
> 用 `ctypes` 调用系统 liblzo2（Linux/macOS 自带）。

### 2. 运行

```bash
pip install -r requirements.txt     # PySide6
python main.py oxford.db
```

按 `Ctrl+Shift+M` 唤起搜索。

## 🎨 交互细节

- **透明度**：窗口失焦后 `opacity` 降到 0.12（近乎透明且仍置顶）；鼠标移入立即恢复 1.0 并重新聚焦输入框。
- **拖动**：按住窗口中任意空白处拖动即可移动位置（窗口位置会在类内记忆）。
- **详情**：`Enter` 在搜索框旁打开详情窗口；`Esc` 或点 ✕ 关闭。

## 📦 打包为 Windows EXE

详细步骤见 [build.md](build.md)。核心命令：

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed \
    --add-data "oxford.db;." main.py -n OxfordLookup
```

## 📜 许可

代码采用 MIT 协议。**KG：词典文件 (.mdx) 属于其版权所有者**，不在本仓库内；请使用你自己的正版词典文件。

内置解析逻辑参考了开源 [readmdict](https://github.com/ffreemt/readmdict)。其本仓库未附带明确的许可证文件，原始 readmdict 项目沿用的是 GPL-3.0，故本项目引用该算法时以其实际采用的许可证为准；LZO 解压与解析算法逻辑已内嵌于本项目。