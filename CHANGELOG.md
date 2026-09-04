# Changelog

本项目所有值得记录的变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.8.9] - 2026-09-04

### 🎯 文件过滤默认改回「只显示 .mdx」
- 默认过滤**只看 .mdx**(v0.8.8 误改成 `*.*`)，下拉仍可切「所有文件」。
- **智能兜底**：若当前目录没有任何 .mdx，自动临时显示全部文件并提示
  「本目录没有 .mdx，已显示全部文件」——既保持默认 .mdx，又不会因目录缺
  词典而看不到任何文件。

### 测试
- 编译 / ruff / pytest(20) 全绿；冒烟验证：默认 `.mdx`、有 .mdx 只列 .mdx、
  无 .mdx 自动回退全部+提示，均通过。

## [v0.8.8] - 2026-09-04

### 🧭 文件选择器彻底重做：扁平目录列表，绝不被困在某一层
上一版(v0.8.7)用 QFileSystemModel 树，在 Windows 上仍出现“只能在桌面、看不到
其他目录”的问题。本次弃用树，改成**扁平列表**（QListWidget + os.listdir，
纯 Qt 自带，跨平台行为一致）：
- 每层列表**第一行固定是「↑ 上级目录」**，一点就到父目录看到**所有同级目录**
  （Downloads / Documents / Program Files 等都平铺），随手点进。
- 之后列出当前目录的**全部子目录**(📁可进入)与文件，浏览一目了然。
- 双击进入目录、双击文件直接选定；地址栏/上级按钮照常。
- 过滤默认「所有文件」保证任何文件都可见，仅想看词典时切 `.mdx`。

现在选择 .mdx 时可像文件管理器一样任意逐层跳转，不会再"找不到其他目录"。

### 测试
- 编译 / ruff / pytest(20) 全绿；offscreen 冒烟覆盖：上级入口、子目录平铺、
  进入/上级回退、跨层跳到兄弟目录、双击文件选定 全部通过。

## [v0.8.7] - 2026-09-04

### 🧭 文件选择器真正能「全局浏览目录」了
此前只能钉在当前目录，点「上级」看不到平级的其他目录(如 Downloads/Program Files)，
不便跳转。本次重构导航：
- 树根改为**当前目录的父目录**：当前目录与其**所有同级目录同层平铺可见**，
  一眼能看到 Downloads、Documents 等并随手进入。
- 双击任意目录即可进入其内部逐层下钻；「上级」「转到」`地址栏` 动态导航。
- 当前目录仍自动展开，直接可见其内部文件/子目录。

现在用户在选择 .mdx 时可像资源管理器一样在整盘自由浏览、跳到任意目录选文件。

### 测试
- 编译 / ruff / pytest(20) 全绿；冒烟验证：树根=父目录、同级目录可见可进、
  双击进入、上级回退、文件选择 全部通过。

## [v0.8.6] - 2026-09-04

### 🐞 三个修复（文件选择器可见性 + 搜索空输入 + 启动可见）
1. **文件选择器默认显示所有文件**：此前默认只显示 `*.mdx`，当前目录没有 .mdx 时
   文件被全部过滤，只见目录/看不到任何文件。现在默认「所有文件」一定可见，
   想只看词典再在下拉切回 `.mdx`。
2. **输入空格回车不再误开上一个词**：输入框为空(或只剩空格)时，回车不再把列表里
   残留的上一词当作选中项打开详情；输入/收起时会清空结果与选中。
3. **索引构建完成后窗口强制可见置前**：个别环境下窗口淡入未推进会卡在近似透明、
   像“没打开软件”。现构建结束强制不透明置前(并写 `[bootstrap] window force-visible`
   日志，便于进一步定位)。

### 测试
- 编译 / ruff / pytest(20) 全绿；冒烟验证选择器默认过滤=所有文件、下拉默认「所有文件」。

## [v0.8.5] - 2026-09-04

### 🎨 文件选择器体验优化
- **名称列不再窄、且可手动拉宽**：文件选择对话框(table中)现在显示表头，文件名
  列**自动占满整个窗口宽度**（永远够宽看清长文件名）；同时列宽设为**可交互拖拽**，
  你也能手动拉宽/收窄。隐藏了「大小/类型/修改日期」这些对选 .mdx 无关的列，界面更清爽。

### 测试
- 编译 / ruff / pytest(20) 全绿；offscreen 冒烟验证：表头可见、名称列占满视图
  宽度(596≈598)、ResizeMode=Interactive 可拖。

## [v0.8.4] - 2026-09-04

### 🐞 修复：MDX 词典选择对话框（实机定位根因）

**根因（v0.8.3 诊断版确认）**：`QFileDialog` 的原生模式在你的 Windows 上，
`exec()` 打开底层 Shell/COM 文件选择器时会随机爆 `0xC0000005`（ACCESS_VIOLATION）
——诊断日志显示所有 `[ask]` 断点都走完、唯有 `exec()` 阶段崩，且崩溃地址每次
不同(野指针)。而 `QFileDialog` 自绘模式虽不崩，却无法正常浏览磁盘/看不到文件。

**解决方案**：彻底弃用 `QFileDialog`，改用**全新自绘文件选择窗口**(纯 QWidget)：
- 地址栏（可键入/粘贴任意路径 + 「上级」+「转到」）
- `QFileSystemModel` 文件树 —— **可正向浏览整个磁盘任意目录**、双击进子目录
- 默认只显 `.mdx`（也可切「所有文件」）、目录始终可见
- 未点文件直接确定时自动选当前目录第一个 `.mdx`

全程不碰原生 Shell/COM 对话框 → **既稳定(不崩)又能浏览磁盘**。同时移除
v0.8.3 加入的对话框诊断埋点（日志更干净）。

### 测试
- 编译 / ruff / pytest(20) 全绿；offscreen 冒烟覆盖构造、路径导航、文件选中、
  空白自动选、真实 `exec()` 交互，均通过。

## [v0.8.3] - 2026-09-03 (诊断版)

### 🔬 诊断：定位「首次打开原生层随机崩溃」的真凶

`v0.8.2` 把文件对话框改回原生后，用户在 Windows 上遇到**随机 `0xC0000005`
(ACCESS_VIOLATION)**：原生 `QFileDialog` 有时能弹、有时一弹就静默崩（无任何
日志堆栈）。本版只加诊断不改行为：

- **文件对话框内部逐行打点**：`_ask_mdx_path` 在确定弹框的每个关键调用前后都写
  `[ask] ...` 到 log —— 崩溃后能精确看到「崩到构造 / set / show / exec 哪一步」。
- **崩溃探照灯升级**：原生崩溃地址改为**十六进制 + 反解所在 DLL 模块名**
  (如 `Qt6Widgets.dll` / `comdlg32.dll` 等)，直接判断是否对话框/COM 层崩溃。

导入方式与 v0.8.2 相同。若再崩，请把 `WordLookup.log` 发回，日志里的
`[ask]` 断点 + `[crash:native] ... [mod=xxx.dll]` 组合即可一锤定位。

## [v0.8.2] - 2026-09-03

### 🐞 Bug 修复（首次选词典 + 首次打开体验）

- **修复「文件选择窗口无法浏览电脑上任何位置、只能选 exe 所在目录；目录里的 .mdx 也看不见」**：
  之前强制 Qt 自绘对话框(`DontUseNativeDialog`)，它当初是为了绕开"原生对话框闪瞬"，但该
  根源(启动时序)早已修复，而自绘对话框在 Windows 上浏览磁盘极不可用。已改回**原生 Windows
  对话框**——现在可以正常浏览整个电脑任意位置选 .mdx。
- **新增崩溃探照灯**：某些环境下首次打开会静默崩溃(原生层、无任何日志堆栈)。本次给 exe
  加了两层兜底——① `sys.excepthook` 把回调/槽里未被捕获的 Python 异常写入 log；
  ② Windows 原生崩溃(如 `ACCESS_VIOLATION`)会记录异常码 + 触发地址到 `WordLookup.log`。
  若你仍遇到崩溃，日志末尾会出现 `[crash:native] ...`，据此即可精准定位。

### 测试
- ruff / pytest(20) / 编译全绿；对话框改原生仅影响首次选词典路径。

## [v0.8.1] - 2026-09-03

### ⚡ 性能优化（代码热路径瘦身，行为与外观零变化）
对 v0.8.0 稳定版做一轮纯性能优化，全部是内部实现优化，**界面/交互/词典数据完全不变**：

- **列表绘制提速**：结果行委托 `paint()` 每帧创建的 7 个 `QFont`/`QColor` 提前到构造时预构建，
  词性图标查表改类级常量 + 单次分词 —— 上下滚动/拖动时每帧少建大量 Qt 对象。
- **详情打开提速**：`dict_render` 全部 15 条正则模块级预编译（不再每次打开详情重新编译）；
  `lookup` 结果与详情渲染加双层 LRU 缓存(各 64/128) —— 来回切换同一词条不重复查库/渲染。
- **构建提速**：索引构建期 `extract_summary` 改为线程本地复用单个解析器（免去每词条新建
  parser）；建库连接加 `temp_store=MEMORY + locking_mode=EXCLUSIVE` —— 首启/重建索引更快。
- **词性归一查表**：`_norm_pos` 合并为单次 O(1) 字典查找。

### 测试
- ruff / pytest(20) / Windows offscreen 冒烟全绿；性能改动行为零变化（纯提速）。

## [v0.8.0] - 2026-09-02

### 🎉 稳定版：0.7.x 系列长期攻坚收尾，中文渲染等相关小 bug 基本修完
从 v0.7.19 起连续多轮解决的「中文在搜索框/列表/详情的显示与布局」问题，到 v0.7.25
已彻底根治，现将累积修复固化为 **0.8.0 稳定版**。主要完成：

- **根治中文渲染/布局错乱**（v0.7.19~0.7.25 六轮）：
  中文字形回退（`QFont.setFamilies`）、输入框/列表给足中文行高、窗口误收起的根因
  修复(IME 组合态触发 `_collapse` → `show` 时有内容强制展开)。此前"中文只露一半 /
  下移重叠 / 放大镜被挤 / 空态行塌"等表现全部归一为正常。
- **发布体验**：Release 自动从 `CHANGELOG.md` 提炼当前版本中文说明发布（不再只是
  commit 列表）；删除了一批有问题的旧 release，发布列表干净、最新版即稳定版。

### 测试
- 新增根治性回归「折叠三角」（模拟窗口被误收起后 show 能正确展开），
  ruff / pytest(20) / Windows offscreen 冒烟 全绿。

## [v0.7.25] - 2026-09-02

### 修复（真正的根因：窗口被 IME 组合「误收起」，导致中文/放大镜/列表全挤进矮框）
- **诊断定型**(v0.7.24 几何日志)：用户实机 `[geo:*]` 读数对比 — 正常时 `win=700x428`
  (展开)、放大镜 `mag.y=28`、列表 `list_top=75`；触发 bug 时 `win=700x76`(收起)、
  `mag.y=14`、列表几乎无空间。**所有「中文下移、放大镜上移、列表矮、重叠」症状 =
  窗口从展开态(428px)掉到收起态(76px)，各控件被暴力塞进 76px 里挤出来的**。
- **根因链条**：「Ctrl+A 全选 → 直接输入中文(IME 组合)」进行中，组合态会把输入框
  `text()` 短暂置空 → `_do_search` 里 `if not q: _collapse()` 被误触发 →
  `_expanded=False` 且窗口立即收到 76px；随后 `show_window` 又因为 `_expanded 为 False`
  走 `_animate_height(H_COLLAPSED)` → 窗口永久停在收起态。中文/放大镜/列表全被挤矮。
  (与字体、IME 组合残留、行高、布局全文**无关** — 之前的 4 版修复方向错误)
- **修复**：`show_window` 在**输入框仍有内容(txt 非空)时强走 `_expand()`**(以「有无内容」
  而非 `_expanded` 标记为准)。只要输入框有中文，显示就必定展开到 428px; 输入框为空才收
  起成窄条(符合设计)。`_expand()` 仅在未展开时执行动画, 已展开则不变, 无副作用。

### 测试
- `smoke_test.py` 新增根治性回归「折叠三角」：模拟 `_expanded=False` + 窗口 76px +
  输入框有中文 → `show_window` 后断言回到 `>=420px`(展开)，不再停在收起态。

## [v0.7.24] - 2026-09-02

### 诊断版（非修复）—— 为定位「中文 + 放大镜被挤/偏移」的 Windows 专属 bug 采集真实几何
- 用户实机反馈：中文在输入框被垂直裁/偏移，**且放大镜图标也被往上挤一点** —— 这推翻了
  之前的"字体/IME/行高"假设：不是单个控件文本绘制问题，而是**整个顶部布局行发生了几何偏移**。
- 本版新增**几何诊断钩子**：每次 `show_window` / `reveal` / `hide_window` 时，把
  窗口、输入框、放大镜、列表的**精确 pos/geometry** + 输入框字体 metrics 写入
  WordLookup.log（形如 `[geo:show] win=... title=... mag=... list_top=...`）。
  - 用户用 bug 触发步骤跑一次，比对「正常一次」与「出 bug 一次」的 `[geo:*]` 读数，
    即可从真实坐标一步锁定偏移是发生在窗口/布局/输入框哪个层级。
  - `SearchWindow.debug_log` 由 main 装配为 `write_log`；默认 None(静默)。
- **为什么不再盲改**：连续 4 版(字体串/setFamilies/IME/行高+布局)均未解决且方向被
  「放大镜也上移」否定，继续盲发意义不大。本版用真实几何数据一次性定性。

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