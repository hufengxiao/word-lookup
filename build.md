# 打包为 Windows EXE

本项目面向 Windows 单机使用。推荐打成**单个 exe**，首次运行时自动让你选择 `.mdx`
词典并构建索引，之后即查即用——不需要用户装 Python。

## 环境（在 Windows 上操作）

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
# 重要：Windows 上 LZO 解压依赖 python-lzo（有官方 win wheel，无需编译）
pip install python-lzo
```

## 方式 A：发布「通用 exe」，用户自己选 mdx（推荐）

不带任何词典打进去，exe 首启弹窗让用户选择自己的 `.mdx` 并自动构建。

```bat
pyinstaller --noconfirm --onefile --windowed ^
  --name WordLookup ^
  --collect-all lzo ^
  --add-data "dictionary;dictionary" ^
  main.py
```

> `--collect-all lzo` 把 `python-lzo` 的 C 扩展 `.pyd` 一起打进去，
> 这样 exe 在 Windows 上能解压 LZO（构建词典时必需）。

用户拿到 `dist/WordLookup.exe` 后：双击 → 首次会弹窗让你选 `.mdx` → 自动构建
`oxford.db`（与 exe 同目录）→ 用 `Ctrl+Shift+M` 唤起查词。

**给用户的说明**：exe 同目录下会生成一个 `oxford.db`，是词典索引，变大属正常。

## 方式 B：把已构建好的 oxford.db 打进 exe （⚠️ 已废弃，不推荐）

> **不推荐**。PyInstaller `--onefile` 会把 `--add-data` 的内容解包到临时目录
> `sys._MEIPASS`，而 `main.py` 的 `_app_root()` 对 frozen 版只认 exe 所在目录，
> 内置 db 需要额外读取逻辑才能生效，当前实现**读不到**。请改用「方式 A」
> 或「精简做法」在 exe 旁放 `oxford.db`。若确需内嵌，需自行改动
> `_app_root()/_db_path()` 同时考虑 `_MEIPASS`，此处不再展开。

如果你希望开箱即用（内置你指定的词典），先把词典转好：

```bat
python -m dictionary.indexer "你的词典.mdx" oxford.db
pyinstaller --noconfirm --onefile --windowed ^
  --name WordLookup ^
  --collect-all lzo ^
  --add-data "oxford.db;." ^
  --add-data "dictionary;dictionary" ^
  main.py
```
(注：`--add-data "oxford.db;."` 及 `_MEIPASS` 的读取缺陷见上方「已废弃」说明)

## 精简做法：exe + 旁边放 db

把已构建的 `oxford.db` 与 exe 放同一目录即可（`main.py` 会自动在 exe 旁找
`oxford.db`）。这是最不容易出问题的分发方式。

## 常见问题

**Q: exe 首启构建时报「找不到可用的 LZO 后端」？**
A: 打包时漏了 python-lzo，或 `--collect-all lzo` 未生效。重装 `python-lzo`
   并确保打包命令含 `--collect-all lzo`。

**Q: 热键没反应？**
A: `Ctrl+Shift+M` 可能已被其它程序占用。改 `main.py` 里的 `GlobalHotkey` 参数换键。

**Q: 详情页样式不完整？**
A: 词典引用的 `oald10.css/js/图` 在原 `.mdd` 资源里，本工具以轻量
   `QTextBrowser` 渲染文字为主。如需完整排班可换 `QWebEngineView`（体积明显增大）。

**Q: exe 报毒/被杀软隔离？**
A: PyInstaller 单文件 exe 常被误报。可用 `--onedir` 替代 `--onefile` 减少误报，
   或在杀软中加入信任。