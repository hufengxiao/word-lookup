# 打包为 Windows EXE

本项目面向 Windows 单机使用，建议打包成单个可执行文件，无需用户装 Python。

## 环境

在 **Windows** 上操作（或任意装了 Python 的机器）：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
```

## 1. 准备词典数据库

```bash
# 需要 readmdict + python-lzo + lxml（Windows 有 wheel）
pip install readmdict python-lzo lxml
python -m dictionary.indexer "你的词典.mdx" oxford.db
```

## 2. 打包单文件 exe

```bash
# --onefile    -> 单个 exe
# --windowed   -> 不弹控制台
# --add-data   -> 把 oxford.db 打进 exe 同级目录
pyinstaller --noconfirm --onefile --windowed ^
  --name OxfordLookup ^
  --add-data "oxford.db;." ^
  main.py
```

生成的可执行文件在 `dist/OxfordLookup.exe`。

> 若希望每次打包都自动把最新词典带进去，可把 `oxford.db` 放到项目根目录
> 再执行上面的命令（`;.` 表示放到 exe 目录）。

## 3. 分发

- `dist/OxfordLookup.exe` 可直接双击运行。
- 词典已内置（通过 `--add-data`），无需额外文件。
- 由于用了 `RegisterHotKey`，运行时会注册系统级热键 `Ctrl+Shift+M`。

## 常见问题

**Q: exe 运行时提示缺少词典数据库？**
A: 检查 `oxford.db` 是否通过 `--add-data` 打入。亦可把 `oxford.db` 与 exe 放同一目录。

**Q: 热键没反应？**
A: 检查是否被其它软件占用 `Ctrl+Shift+M`。可修改 `main.py` 里的 `GlobalHotkey` 参数改键。

**Q: 详情页样式不完整？**
A: 词典 HTML 引用了 `oald10.css/js`（在配套 `.mdd` 中），此处以轻量 `QTextBrowser` 渲染文字为主。如需完整排版，可自行扩展用 `QWebEngineView`（体积会增大）。