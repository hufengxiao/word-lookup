# Changelog

本项目所有值得记录的变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.7.23] - 2026-09-02

### 修复（v0.7.22 让中文显示完整后，引发的布局几何问题）
- v0.7.22 把输入框 minimumHeight 提到 ≥45px(容纳中文实心字形) 后，中文完整显示了，
  但暴露出：
  1. **中文"位置下移"并与搜索列表文字重叠** —— 顶部输入行(top margins 12+12 +
     输入框≈45) ≈ 69px 超过了旧窗口收起高度(H_COLLAPSED=68)，输入框溢出下界并压到
     列表起点；
  2. **搜索结果列表可视区被挤矮**：窗口固定总高不变，输入框多占的高度从列表区扣除。
- **修复**：
  1. **窗口高度恒量上调**给输入行留裕量：`H_COLLAPSED 68→76`、`H_EXPANDED 420→428`、
     `H_DETAIL 660→668`（收起档 69px 输入行 + 7px buffer；展开/详情档在收起档上方
     保持原列表/详情区高度）。
  2. **高度动画每帧后 `layout().activate()`**：Windows 无边框置顶窗口在 fixedSize+resize
     动画下布局不总是即时重排，子控件(输入框/列表/详情)会停在旧几何 → 中文与列表重叠。
     强制布局每帧重排，彻底消除重叠。

### 测试
- `smoke_test.py` 新增回归：展开态下断言「列表 geometry.top() >= 输入框 bottom()」
  （**不重叠**——专门防"中文与列表文字重叠/被挤矮"复发）。

## [v0.7.22] - 2026-09-02

### 修复（问题2 真正根因：靠用户实机反馈确认是**垂直裁切**成「只剩中间一条」）
- 基于用户实机确认（截图反推「只看到字符的中间一条；英文完全正常、列表空态也矮」）：
  这不是字体回退问题，也不是 IME 组合态，而是**控件/行高不足以容纳中文汉字的实心方块字形**。
  - 中文（如微软雅黑）是实心方块，字形上下高度远高于拉丁（Segoe UI）字符；
  - Windows 的 Qt 布局按 ≈拉丁字体 metrics 给 QLineEdit 和 QListView 一个较矮的行高，
    中文超出该高度时**以控件水平中线为中心上下对称**被裁 → 只显示「字中间一条」，
    顶部与底部都切掉；英文（x-height 矮）刚好完整装下，所以英文正常。
- **修复**：
  1. 搜索输入框 `_title.setMinimumHeight(QFontMetrics(中文字体).height() + 16)`（保底 40px）
     + `setAlignment(AlignVCenter)` —— 让输入框高度始终够容纳中文实心字形，不再上下裁切。
  2. 结果列表 `_list.setUniformItemSizes(True)`，并给**每个 item（含空态「没有找到 xxx」与
     候选）显式 `setSizeHint(宽, CJK metrics + padding)`** —— 绕开 QListWidget 对未设
     sizeHint 的行按自身 CJK metrics 算矮行高的默认行为 → 空态/候选行不再塌。
- 保留 v0.20/21 的 `setFamilies` 与 `inputMethod` 清理（无害，对相近路径有益）。

### 测试
- `smoke_test.py` 新增回归：输入框 `minimumHeight()>=40`；列表首项显式 `sizeHint` 高度
  == `_row_h`；继续覆盖 `setFamilies`、IME 清理、空态行高。

## [v0.7.21] - 2026-09-02

### 修复
- **中文只显示上半截（在「Ctrl+A 全选后直接输中文 → 隐藏 → 显示」下必现）的真正根因**：
  - 精确复现：逐步 backspace 删英文后输入中文，隐藏/显示正常；但 **Ctrl+A 全选替换后
    输入中文，再隐藏/显示 → 搜索框里中文被裁(只显示半截)、空态行仍塌**。
  - 根因不是字体（上一版 setFamilies 已修正字体的 metrics——它修了"英文全选替换"之外的
    部分），而是 **Windows 输入法(IME)的预编辑组合(composition)状态**：Ctrl+A 全选替换
    时中文以 IME 预编辑态进行，若在组合未上屏/未清理时用快捷键隐藏窗口，该组合上下文
    残留，重新显示找回焦点时中文按被裁剪的预编辑高度重排 → 显示半截。
  - 修复：`hide_window()` / `show_window()` 中先
    `QGuiApplication.inputMethod()commit()` 再 `reset()`，强制提交预编辑文本并清空
    输入法组合上下文，保证显示从干净输入文档开始。

### 测试
- `smoke_test.py` 新增回归：spy `QGuiApplication.inputMethod()` 的 `commit`/`reset`，
  断言 `hide_window()`/`show_window()` 路径上必须各至少调用一次（防止未来误删该修复）。

## [v0.7.20] - 2026-09-02

### 修复
- **彻底修复中文被裁切 + 空态行高塌陷（上一版没真正生效）**：
  - 上一版误用 `QFont("Segoe UI, Microsoft YaHei", …)` —— `QFont(字符串)` 把整条
    当**单一字体名**，找不到名为 `"Segoe UI, Microsoft YaHei"` 的字体，实际只落到
    `Segoe UI`，**中文字体回退从未生效**（搜索框中文仍只显示上半截、空态行仍塌）。
  - 本版改用 Qt6 的 **`QFont.setFamilies(["Segoe UI", "Microsoft YaHei"])`**（真正的
    字体列表回退），分别应用到：
    - `QLineEdit` 搜索框 `_title` `setFont` → 中文不再被裁上半截；
    - **`QListWidget` 结果列表 `_list` `setFont`**：这是空态行高的决定因素——空态项
      `"没有找到 xxx"` 的行高由 QListView 用 `view.font()` 的 `QFontMetrics` 计算
      （**不经 delegate 的 sizeHint**）。上一版只给 styleSheet 加中文 font-family 无效
      （styleSheet 的 font-family 不改变 `widget.font()`），所以空态中文行仍塌成一个字符。
      现在 view.font 含中文字体后，空态行回到正常高度（≥38px）。
    - `_ResultDelegate` 词头/释义字体与 `sizeHint` 改用 `option.font`（=view.font，含中文）。

### 测试
- `smoke_test.py` 回归强化：断言 `_list` 与 `_title` 的 `QFont.families()` **确实含
  `Microsoft YaHei`**（在此之前 styleSheet font-family 做到，setFont 未生效的镜子会
  直接 FAIL，防止回退到上一版的无效修法）+ 空态行高 `sizeHintForRow >= 20px`。

## [v0.7.19] - 2026-09-02

### 修复
- **查不到内容的词条按 Enter 不再误切进详情视图**：`_on_return`/`_current_key` 此前对「无
  真实词条选中」会落回输入框文本（例如输入中文"金额"）并硬切到详情模式，即使该文本查不到
  词条，也会把窗口撑成详情页、显示空占位。现在仅当当前选中项是真实词条（`UserRole` 非空）
  才对 Enter 进入详情；空态占位项/没有匹配时按 Enter 保持列表现状。
- **中文内容被裁切（只显示上半截）+ 空态候选行高塌成一个字符**：`QLineEdit` 搜索框与
  `QListWidget` 结果列表只设了 `Segoe UI`（无中文字形），Windows 上中文回退到其它字体时，
  glyph 按 Latin 行盒渲染被从顶部裁切；结果列表中文候选行高也因此塌成数像素。
  - 搜索框/列表/联想 delegate 全部显式中文字体回退：`Segoe UI, Microsoft YaHei`。
  - `_ResultDelegate.sizeHint` 由硬编码 `42px` 改为用真实 `QFontMetrics(_key_font).height()`
    度量，避免中文 metrics 偏低时行高不足。

### 测试
- `smoke_test.py` 新增回归：
  - 中文无匹配按 Enter → 不切详情（`_mode` 保持 list、详情不可见）。
  - 空态项行高 `sizeHintForRow >= 20px`，不再塌成仅一个字符高度。

## [v0.7.18] - 2026-09-02

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