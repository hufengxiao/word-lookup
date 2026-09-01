# Changelog

本项目所有值得记录的变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 重构
- **精简 MDX 解析器死代码**：移除从未被调用的 `MDX.lookup()`/`get_all()`/`key_texts()`/`build_lookup_table()`/`get_by_key_id()`。GUI 查词走 SQLite `Searcher`，索引构建走流式 `_iter_record_blocks()`，这些遗留接口（其中 `lookup` 还是线性扫描全词条）留着是隐患。
- **去重 summary 回填逻辑**：`main.py` 的 `_run_backfill` 与 `indexer.backfill_summary` 内容重复，归一为后者，并新增可选 `progress` 回调（GUI 主线程用它 pump 事件保持响应）；`main.py` 删除重复实现。
- **`--version`/`-v` 处理抽取**：提炼为 `_cli_version_flag()`，消除源码/Qt 分支的冗余 `QApplication` 初始化。

### 修复
- **词性缩写无法归一（潜伏 bug）**：`summary._ALIAS` 字典构造方向写反（`{完整名: 缩写}`），导致 `n`/`v`/`adj` 这类单字母缩写词性永远无法被归一为规范名（因牛津 class 通常已是完整名 `noun`/`verb` 而被掩盖）。修正为 `{缩写: 完整名}`。
- **词性前缀匹配歧义**：`_norm_pos` 兜底从"首个命中即返回"改为"取最长前缀匹配"，消除短规范词命中顺序不定造成的歧义。

### 变更
- **补了测试覆盖空白**：新增 `tests/test_searcher_summary.py`（14 用例），覆盖 `Searcher.search`（前缀/大小写/limit/空查询）、`lookup`（精确/缺失/`@@@LINK` 重定向）、`summary`（词性归一/摘要/截断）、`indexer.backfill_summary`（补列+幂等）。此前 CI 只测渲染器。
- **lzo 后端缓存句柄**：LZO 解压后端只在首次探测时 `CDLL()` 一次并缓存句柄，避免对词典百万级词条重复加载动态库。
- **结果列表跳过重复渲染**：查询建议与上次完全相同（如回退到已见前缀）时不再重建列表，保留当前选中/滚动位置。
- **打包配置**：PyInstaller 关闭 UPX（`upx=False`，降低杀软误报）；`pyproject.toml` classifier 改为 `OS Independent`（库实际跨平台）。

## [v0.7.17] - 2026-09-01

### 修复
- **修复 v0.7.16 回归**：`--version`/`-v` 弹窗崩溃。统一 About 对话框时误把 `QApplication` 实例当作父对象传给 `QMessageBox`（Qt 不接受非 QWidget 的父对象），导致报错。现改为无父窗口的顶层弹窗；托盘「关于/版本信息」不受影响。

## [v0.7.16] - 2026-09-01

### 重构
- **统一版本 / 关于对话框**：把 `--version`/`-v` 的版本弹窗与托盘「关于 / 版本信息」合并为同一个 `_show_about()` 实现，文案与样式完全一致，单一维护点。

## [v0.7.15] - 2026-09-01

### 新增
- **托盘右键「关于 / 版本信息」**：常驻托盘图标右键即可查看版本号（`get_version()`，单一来源），不用再跑命令行。
- **`--version` / `-v` 行为收敛**：直接显示版本对话框（GUI 程序标准行为，稳定、不闪黑框）；有真实控制台时才终端打印。

### 变更
- 移除不可靠的 windowed exe `AttachConsole` 打印路径（经多版本 + CI runner 实测，PyInstaller `--windowed` 无法可靠打印到父终端）。

## [v0.7.14] - 2026-09-01

### 修复
- **`--version` 终端打印真正的根因**：windowed exe 接回父终端时，把 Win32 `HANDLE` 误当 POSIX `fd` 传给 `io.FileIO`（类型不符必然抛错回到弹窗）。修复为 `msvcrt.open_osfhandle(HANDLE, O_WRONLY)` → `os.fdopen()` 正确转换。请在本机交互终端的 PowerShell / Windows Terminal 实证：
  ```powershell
  .\WordLookup.exe --version
  # 期望直接打印: Word Lookup 0.7.14  (不再弹窗)
  ```
- CI 增加 `--version` 输出探针 step（诊断用，不阻塞发布）。

## [v0.7.13] - 2026-09-01

### 修复
- **根治版本号错位**：版本改为**单一来源**——CI 在发布打包时把 git tag 版本注入 `version.txt`（随 exe 打包），程序启动读取该文件。从此 exe 报告版本 = 该次发布 tag，彻底告别"下载 v0.7.11 却显示 v0.7.9"。
- **`--version` 不再闪黑框/不弹慢窗**：优先直接打印到父终端（`AttachConsole` 接回 PowerShell/Windows Terminal/cmd）；仅当确实无法附加终端（如双击运行）才走 Qt 模态弹窗。移除了旧的 `AllocConsole`（会凭空弹出一闪而过的黑框）。

## [v0.7.12] - 2026-09-01

### 修复
- **`--version` 从终端启动时直接打印到终端**（而非弹窗）：windowed exe 通过 Win32 `AttachConsole(ATTACH_PARENT_PROCESS)` 把标准输出接回 PowerShell / Windows Terminal / cmd，立即打印 `Word Lookup <ver>` 后退出；仅当无法附加控制台（如双击运行）才退化为 Qt 弹窗。
- **版本号显示错误**：修正 exe 报告的版本与其 release 版本不一致的问题（此前 v0.7.11 误报 0.7.9）；`__version__` 与 pyproject.toml 对齐为 0.7.12。

## [v0.7.10] - 2026-09-01

### 新增
- **命令行 `--version` / `-v`**：`WordLookup.exe --version` 打印版本号后退出（无需启动 GUI）。
- **集中版本号** `__version__`：main.py 与 pyproject.toml / GitHub tag 同步，便于排查已安装 exe 的版本。

## [v0.7.11] - 2026-09-01

### 修复
- **windowed exe 中 `--version` 弹窗**：不再仅靠 `print`（windowed 无控制台看不到），改为 Qt 弹窗展示版本。
- **修复启动 UnboundLocalError**：`--version` 分支内的局部 `import QApplication` 遮蔽全局同名绑定，导致正常启动崩溃；改为仅局部导入 `QMessageBox`。
- CI 冒烟（exe 启动存活）纳入回归防护。

## [v0.7.9] - 2026-09-01

### 工程化 / 质量
- **CI 重构**：lint + 单元测试在 Python 3.11/3.12/3.13 矩阵跑（`ruff check` + `pytest tests/`）；pip 依赖缓存加速；job 超时保护；并发构建用 `concurrency.cancel-in-progress` 防踩踏；release 仅 tag 触发。
- **单元测试**：新增 `tests/test_dict_render.py`（例句配对 / oT 中文容器 / 无例句不硬凑 / style 位置 / idm 样式 / shcut 防污染 6 项）。
- **ruff 收敛**：新增全局 ruff 配置（务实规则 + 防御性例外），代码库 `ruff check` 清零。
- **`pyproject.toml`（PEP 621）**：项目元数据、依赖、dev extras、ruff/pytest 配置集中管理。
- **文档**：README 补全项目结构、加 CI/许可徽章；build.md 的「方式 B 内置 db」标注废弃并存原因；新增 `CHANGELOG.md`、MIT `LICENSE`（M 系列改进）。

## [v0.7.8] - 2026-09-01

### 修复
- **子义项小标题不污染释义中文**：超长多义动词（run/light/take）的 `<h2 class="shcut">`（如 `manage 管理`）不再把其中文拼进上一条释义的中文行（修复 `管理；经营管理`、`提供，开设…公共汽车；火车` 这类尾部杂字）。

## [v0.7.7] - 2026-09-01

### 修复
- **惯用语/短语词条保留样式**：以 `<span class="idm">` 作词头（如 `fuck me`）或缺少 `<h1 class=headword>` 的词条，不再掉进无样式兜底，详情页有完整深色排版；未知结构的兜底也套用统一样式，避免白屏。

## [v0.7.6] - 2026-09-01

### 修复
- **例句中文支持 `oT` 容器**：牛津例句翻译可能用 `<xT>/<aT>/<oT>` 三种容器，此前漏掉 `oT` 导致部分例句（如 `normal distribution`）没翻译。现统一识别。

## [v0.7.5] - 2026-09-01

### 修复
- **无例句块的词条不再"一大坨"**：没有标准 `<ul class="examples">` 的词条（如 `General American`）不再被整词条正文硬凑成一条超长例句，干净显示、无 EXAMPLE 区。

## [v0.7.4] - 2026-09-01

### 修复
- `<style>` 统一定位到 `<head>` 内，避免部分 Qt 版本把 CSS 声明当正文文本（详情页出现"一堆 div"）。
- 例句英文提取退化分支不再残留 `<span class="gloss">` 这类空开标签（显示为裸标签文本）。

## [v0.7.3] - 2026

### 改进
- 统一中英文字体（`Segoe UI` / 微软雅黑）与色板，词条详情与搜索界面观感一致。

<!-- 以下为早期版本，仅记录关键节点 -->

## [v0.7.0] - 2026

### 新增
- Spotlight 动效抛光：屏幕自适应宽度 + 假毛玻璃浮层 + 透明度渐变 + 唤起浮现动画。

## [v0.5.0] - 2026

### 变化
- 详情改为单窗口内嵌切换（Enter 在列表 ↔ 详情之间），不再额外弹窗。

## [v0.3.x] - 2026

### 新增
- 联想结果带基础释义预览（词头 + 一行中文摘要）。
- 词典库 schema 就地迁移，无需重下。

## [v0.1.0] - 2026-08-19

### 新增
- 首个可用版本：全局热键 + Spotlight 搜索 + MDX 词典构建 + SQLite 索引 + Windows exe 打包。

[unreleased]: 尚未发布
[v0.7.8]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.8
[v0.7.7]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.7
[v0.7.6]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.6
[v0.7.5]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.5
[v0.7.4]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.4