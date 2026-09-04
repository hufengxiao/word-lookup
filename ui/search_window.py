"""Spotlight 风格的搜索主窗口。

交互（对齐 macOS Spotlight）：
  - 唤起即见一个长条搜索框；输入后下方展开结果列表
  - ↑/↓ 选择 · Enter 打开详情 · Esc 隐藏
  - 失焦 → 近乎透明；鼠标移入 → 恢复不透明
  - 按住输入框旁的空白/底栏可拖动窗口

背景用 QPainter 手绘（不依赖样式表 rgba 背景映射），确保卡片底色在
Windows + 无边框置顶窗口下稳定可见。
"""
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QLinearGradient,
    QPainter,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QTextBrowser,
    QVBoxLayout,
)

from dictionary.searcher import Searcher

# 透明状态
OPACITY_ACTIVE = 1.0      # 正常（唤起/鼠标移入）
OPACITY_FOCUS_LOST = 0.10  # 近乎透明（失焦）

MAX_SUGGEST = 20
SEARCH_DELAY_MS = 60      # 输入去抖
CARD_RADIUS = 14
# 尺寸改为按屏比例自适应（不再硬编码固定像素，任何桌面都“刚刚好”）
W = 520                      # 基准宽，实际按屏幕比例取
# 窗口总高度。v0.7.22 输入框 minimumHeight 提到至少 45px(容纳中文实心字形)后，
# 顶部输入行(top margins 12+12 + 输入框≈45) ≈ 69px，会超过旧 H_COLLAPSED(68) 导致
# 输入框溢出下界、中文与列表文字重叠、列表可用高度被挤矮。故各档位上调，给输入行
# 留出足够裕量（收起档约 69px 输入行 + 7px margin buffer → 76px）。展开档在收起档
# 基础上保持原有差量(列表/详情区高度不变)。
H_COLLAPSED = 76
H_EXPANDED = 428
H_DETAIL = 668

def _scale_width():
    """窗口宽度随屏幕可用宽度缩放，锁定在 [420, 700] 区间（Spotlight 居中偏上）。"""
    try:
        from PySide6.QtWidgets import QApplication
        sc = QApplication.primaryScreen()
        if sc is not None:
            w = sc.availableGeometry().width()
            return max(420, min(700, int(w * 0.42)))
    except Exception:
        pass
    return W

# 透明度（渐变阈值）
OPACITY_ACTIVE = 1.0
OPACITY_FOCUS_LOST = 0.10
# 渐变时长(ms) / 帧间隔(ms)：失焦淡出 + 悬停/唤起淡入 都走这条曲线
FADE_MS = 160
FADE_STEP = 16

# 统一字体：英文/数字=Segoe UI，中文=微软雅黑（全 App 一致，不再散乱定义）
FONT_FAMILY         = "Segoe UI"
FONT_FAMILY_CJK     = "Microsoft YaHei"
# 统一色板（苹果设计语言，克制的层级：只用明度分层，蓝色仅作唯一强调）
CLR_TEXT            = "#F2F2F7"   # 主文本（系统上）
CLR_TEXT_SECONDARY  = "#9AA0A6"   # 次级文本（系统灰）
CLR_TEXT_TERTIARY   = "#6E6E73"   # 弱化/标签
CLR_ACCENT          = "#0A84FF"   # 唯一点缀色（苹果蓝）：词性/选中/强调
CLR_SEL_BG          = (42, 97, 168, 255)   # 选中行背景：雅致的苹果蓝偏深
CLR_CARD            = "#1E1E24"   # 卡片/详情底色


class _MagnifierLabel(QLabel):
    """Apple 风格放大镜：细圆环 + 45° 手柄，QPainter 矢量手绘，替换掉 emoji。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QColor(255, 255, 255, 170)
        # 圆环
        r = 6.5
        c = QPoint(10, 8)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(c), r, r)
        # 45° 手柄：从圆环右下延伸到左下
        p.drawLine(QPointF(c.x()+4.4, c.y()+4.4),
                   QPointF(c.x()+9.2, c.y()+9.2))
        p.end()


class _ResultDelegate(QStyledItemDelegate):
    """Spotlight 式结果行：词头加粗醒目 + 右侧紧跟灰色释义预览。

    单词用大字、亮白(选中时)，释义用较暗的灰/浅青色并在空间不足时省略。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # 中英文字体栈：必须用 setFamilies（QFont("A, B") 不会回退到中文）。
        self._key_font = self._make_font(15, QFont.Bold)
        self._sum_font = self._make_font(13, QFont.Normal)
        # 统一色板：主文本白，选中时纯白，未选中次级灰；释义预览一律敲会灰(不再用橙色)
        self._bg_on = QColor(*CLR_SEL_BG)
        self._key_on = QColor(CLR_TEXT)
        self._key_off = QColor("#FFFFFF")
        self._sum_on = QColor(255, 255, 255, 220)
        self._sum_off = QColor(CLR_TEXT_SECONDARY)
        # P0-1 性能：paint() 热路径对象预构建，避免每帧新建 QFont/QColor/QRect
        self._ic_font = QFont(FONT_FAMILY, 9, QFont.DemiBold)
        self._hint_font = QFont("Segoe UI", 9, QFont.Normal)
        self._icon_bg_on = QColor(255, 255, 255, 46)
        self._icon_bg_off = QColor(255, 255, 255, 20)
        self._icon_fg = QColor(255, 255, 255, 210)
        self._hint_bg = QColor(0, 0, 0, 66)
        self._hint_fg = QColor(255, 255, 255, 195)

    @staticmethod
    def _make_font(pt: int, weight: QFont.Weight):
        f = QFont()
        f.setPointSize(pt)
        f.setWeight(weight)
        f.setFamilies([FONT_FAMILY, FONT_FAMILY_CJK])
        return f

    def sizeHint(self, option, index):
        w = max(option.rect.width(), 320)
        # 行高用 option.font(=view.font，含中文回退) 的真实 metrics，
        # 保证中文候选行高足够、不塌成一个字符。
        fm = QFontMetrics(option.font)
        h = max(38, fm.height() + 14)
        return QSize(max(w, 320), h)

    def paint(self, painter, option, index):
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # 选中背景 (圆角)；未选中时把背景填成卡片色(透明交给窗口)
        painter.setPen(Qt.NoPen)
        if selected:
            painter.setBrush(self._bg_on)
            painter.drawRoundedRect(r, 9, 9)

        key = index.data(Qt.UserRole) or (index.data(Qt.DisplayRole) or "")
        summ = index.data(Qt.UserRole + 1) or ""
        # 行类型：从释义预览首词推断词性（n/v/adj/adv/pron 等），无则显示首字母大写
        row_type = self._row_type(summ, key)

        kc = self._key_on if selected else self._key_off
        sum_color = self._sum_on if selected else self._sum_off

        # #5 类型图标：左侧一个小圆角方形，内放词性缩写
        icon_x = r.left() + 8
        icon_size = 22
        icon_cy = r.center().y()
        painter.setBrush(self._icon_bg_on if selected else self._icon_bg_off)
        painter.drawRoundedRect(QRect(icon_x, icon_cy - icon_size // 2, icon_size, icon_size), 6, 6)
        painter.setFont(self._ic_font)
        painter.setPen(self._icon_fg)
        painter.drawText(QRect(icon_x, icon_cy - icon_size // 2, icon_size, icon_size),
                         Qt.AlignCenter, row_type)

        # 词头（留出类型图标占位）
        icon_width = icon_size + 10
        dx = icon_x + icon_width if row_type else 0
        painter.setFont(self._key_font)
        kx = dx + 2
        km = painter.fontMetrics().horizontalAdvance(key) + 8
        painter.setPen(kc)
        painter.drawText(QRect(kx, r.top(), km, r.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, key)

        # #5 Enter 快捷提示：选中时在右侧显示小徽标
        hx = None
        if selected:
            hint = "Enter"
            painter.setFont(self._hint_font)
            hw = painter.fontMetrics().horizontalAdvance("Enter") + 16
            hx = r.right() - hw
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._hint_bg)
            painter.drawRoundedRect(QRect(hx, r.center().y() - 10, hw, 20), 10, 10)
            painter.setPen(self._hint_fg)
            painter.drawText(QRect(hx, r.center().y() - 10, hw, 20), Qt.AlignCenter, hint)

        # 释义（在词头右侧、Enter 徽标左侧之间）
        painter.setFont(self._sum_font)
        painter.setPen(sum_color)
        right_limit = (hx - 8) if hx is not None else r.right() - 4
        avail = right_limit - (kx + km) - 4
        if avail > 0:
            elide = painter.fontMetrics().elidedText(summ, Qt.ElideRight, avail)
            painter.drawText(QRect(kx + km, r.top(), avail, r.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, elide)

    @staticmethod
    def _row_type(summ, key):
        """从释义预览解析词性缩写，作为类型图标内容。"""
        if not summ:
            return key[0].upper() if key else "?"
        parts = summ.split()
        head = parts[0].lstrip(",;").strip().lower()
        # P2 性能：每次 paint 都调用，词性查表用类级常量(不逐帧重建 dict)。
        return _ResultDelegate._ROW_ALIASES.get(head, key[0].upper() if key else "?")

    # 词性缩写参考表（类级常量，避免每帧 paint 里重建 dict）
    _ROW_ALIASES = {
        "n": "n", "noun": "n", "v": "v", "verb": "v", "adj": "adj",
        "adjective": "adj", "adv": "adv", "adverb": "adv", "prep": "prep",
        "pron": "pron", "conj": "conj", "interj": "int", "phr": "phr"}


class SearchWindow(QFrame):
    """Spotlight 式悬浮搜索框。"""

    # 几何诊断钩子：main 装配时设为 write_log，用于在 Windows 上 Dump 触发 bug 时的
    # 精确控件几何(窗口/输入框/放大镜/列表 的 pos/size + 字体 metrics)，一次定位
    # 「中文 + 放大镜垂直偏移」的真实来源。默认 None(静默)。
    debug_log = None

    def _dump_geo(self, stage: str):
        if callable(self.__class__.debug_log):
            try:
                w, t, m, ls = self, self._title, self._mag, self._list
                fg = QFontMetrics(t.font())
                geo = (
                    "[geo:%s] win=%d,%d %dx%d title=(%d,%d %dx%d) "
                    "t_metrics_h=%d lead=%d mag=(%d,%d %dx%d) list_top=%d list_vis=%s"
                    % (
                        stage, w.x(), w.y(), w.width(), w.height(),
                        t.x(), t.y(), t.width(), t.height(),
                        fg.height(), fg.leading(),
                        m.x(), m.y(), m.width(), m.height(),
                        ls.geometry().top(), ls.isVisibleTo(self),
                    )
                )
                self.__class__.debug_log(geo)
            except Exception:
                pass

    def __init__(self, searcher: Searcher, parent=None):
        super().__init__(parent)
        self._searcher = searcher

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self._win_w = _scale_width()          # 按屏幕比例的自适应宽
        self.setFixedSize(self._win_w, H_COLLAPSED)
        self.setWindowOpacity(0.0)            # 开头透明，由唤起动画淡入

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        # ---- 顶部：搜索行（Spotlight 长条核心）----
        top = QHBoxLayout()
        top.setContentsMargins(16, 12, 12, 12)
        top.setSpacing(0)
        self._title = QLineEdit(self)
        self._title.setPlaceholderText("输入英文单词查询…")
        # 必须显式给中文字体：仅 Segoe UI 时 Windows 回退中文字体，其 ascent
        # 与 Latin 行盒不匹配，中文 glyph 会被 QLineEdit 按 Latin 行高从顶部裁切
        #（表现为「中文只显示上半截」）。windows 回退用 setFamilies（不是 QFont(family_str)，
        # 后者把 "A, B" 当整体、不会回退到 Microsoft YaHei）。
        _tf = QFont()
        _tf.setPointSize(19)
        _tf.setFamilies([FONT_FAMILY, FONT_FAMILY_CJK])
        self._title.setFont(_tf)
        # 【关键】量化输入框高度必须给足中文字形空间。Windows 上 Qt/布局常按拉丁
        # (Segoe UI) metrics 计算 QLineEdit 默认高度，纯中文实心方块字形远高于拉丁，
        # 会以控件水平中线为中心上下溢出 → 只看到字的中间一条(上下均被裁)。
        # 显式 minimumHeight = 中文字体 metrics 高度 + 上下留白(也预留 IME 组合下划线)。
        # min-h 用 fontMetrics 动态算, 再 +16 上下 padding, 并保底 40px。
        _tfh = QFontMetrics(_tf).height()
        self._title.setMinimumHeight(max(40, _tfh + 16))
        self._title.setAlignment(Qt.AlignVCenter)
        self._title.setStyleSheet(
            "QLineEdit { background: transparent; color:#FFFFFF; border:none;"
            " selection-background-color:%s; }"
            "QLineEdit::placeholder { color:#6E6E73; font-family:'%s','%s'; }"
            % (CLR_ACCENT, FONT_FAMILY, FONT_FAMILY_CJK)
        )
        self._title.textChanged.connect(self._on_text_changed)
        self._title.returnPressed.connect(self._on_return)
        self._title.setFocusPolicy(Qt.StrongFocus)
        # 拦截 ↑/↓/Enter，实现 Spotlight 式键盘导航（焦点一直在输入框）
        self._title.installEventFilter(self)
        # #11 放大镜：矢量手绘，替换原 emoji
        self._mag = _MagnifierLabel(self)
        top.addWidget(self._mag, 0, Qt.AlignVCenter)
        top.addSpacing(8)
        top.addWidget(self._title, 1)

        # 底部拖动手柄（三条杠），也可直接拖；同时是一个可见的拖动把手
        self._drag_label = _DragHandle(self)

        top.addStretch(0)
        top.addWidget(self._drag_label, 0, Qt.AlignVCenter)
        lay.addLayout(top)

        # ---- 结果列表 ----
        self._list = QListWidget(self)
        self._list.setItemDelegate(_ResultDelegate(self._list))
        # 关键：必须给 view 本身 setFont(setFamilies) 含中文字体。空态项("没有找到 xxx")
        # 的行高由 QListView 用 view.font() 的 QFontMetrics 计算（不经 delegate），
        # 若 view.font 只是 Segoe UI，Windows 对中文回退的 metrics 极低 → 空态行塌成一个字符。
        _lf = QFont()
        _lf.setPointSize(15)
        _lf.setFamilies([FONT_FAMILY, FONT_FAMILY_CJK])
        self._list.setFont(_lf)
        # 【关键】列表行高必须给足中文字形空间。QListView 对未显式设 sizeHint 的空态项
        # ("没有找到 xxx") 用 view.font() metrics 算行高，中文实心方块会高于拉丁 → 行被压矮、
        # 中文上下被裁只剩中间一条。统一点缀: 每行显式 sizeHint = CJK metrics + 垂直 padding。
        # setUniformItemSizes(True) 让所有行(含空态)统一走该高度, 绕开 view 默认栏矮计算。
        self._row_h = max(36, QFontMetrics(_lf).height() + 18)
        self._list.setUniformItemSizes(True)
        self._list.setStyleSheet(
            "QListWidget { background: transparent; color:#e8e8e8;"
            " border:none; outline:none; }"
            "QListWidget::item { margin: 0 8px; }"
        )
        self._list.setSpacing(1)
        self._list.hide()
        self._list.itemActivated.connect(self._open_item)
        lay.addWidget(self._list, 1)

        # ---- 内嵌详情视图：按 Enter 后从"结果列表"切换成"详情"（同一窗口内）----
        self._detail_view = QTextBrowser(self)
        self._detail_view.setStyleSheet(
                    ("QTextBrowser { background: %s; border:none; "
                     "selection-background-color:#0A84FF; selection-color:#ffffff; }"
                     "QScrollBar:vertical{width:8px;background:transparent;}"
                     "QScrollBar::handle:vertical{background:#45454E;min-height:30px;border-radius:4px;}"
                     "QScrollBar::handle:vertical:hover{background:#5A5A6A;}"
                     "QScrollBar::add-line,QScrollBar::sub-line{height:0;}")
                    % CLR_CARD
                )
        self._detail_view.setOpenExternalLinks(True)
        self._detail_view.hide()
        lay.addWidget(self._detail_view, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DELAY_MS)
        self._timer.timeout.connect(self._do_search)

        self._is_active_opacity = True
        self._did_center = False
        self._dragging = False
        self._drag_offset = None
        self._expanded = False
        self._last_query = ""
        self._last_rows = None   # 上次渲染的结果缓存，用于跳过重复重建
        # 透明度渐变状态
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(FADE_STEP)
        self._fade_timer.timeout.connect(self._fade_tick)
        self._fade_target = OPACITY_ACTIVE
        self._reveal_timer = None   # 唤起浮现动画（淡入+上滑+微缩放）
        # 高度动画状态（展开/收起连续动画，替代 setFixedSize 瞬间跳变）
        self._resize_timer = QTimer(self)
        self._resize_timer.setInterval(14)
        self._resize_timer.timeout.connect(self._resize_tick)
        self._resize_from = 0
        self._resize_to = 0
        # 视图状态：'list'（联想列表）/ 'detail'（详情视图）
        self._mode = "list"
        self._current_detail_key = None

        # 透明度巡检器：不依赖 WindowDeactivate/Activate 事件(工具窗常漏发)，
        # 周期性检查「窗口是否正被使用(有焦点或鼠标停留)」来决定透明与否，
        # 彻底避免"移入后一直不透明"的死锁 bug。
        self._op_timer = QTimer(self)
        self._op_timer.setInterval(150)
        self._op_timer.timeout.connect(self._refresh_opacity)

    # ------------------------------------------------------------------
    # 透明度：根据“当前正在使用该窗口”与否，周期性刷新，失焦即透明
    # ------------------------------------------------------------------
    def _start_opacity_watch(self):
        if not self._op_timer.isActive():
            self._op_timer.start()

    def _stop_opacity_watch(self):
        self._op_timer.stop()

    def _transition_opacity(self, target: float):
        """开始向 target 做 160ms 渐变插值（替代原跳变，Spotlight 式跟手淡入淡出）。"""
        self._fade_target = target
        if not self._fade_timer.isActive():
            self._fade_timer.start()

    def _fade_tick(self):
        """每一帧把窗口透明度向目标推进 1 步，到达目标后停止定时器。"""
        cur = self.windowOpacity()
        target = self._fade_target
        if abs(cur - target) < 0.02:
            self.setWindowOpacity(target)
            self._fade_timer.stop()
            return
        # 线性插值，16ms → ~160ms 完成；淡入稍快、淡出同速即可
        step = (target - cur) * (float(FADE_STEP) / FADE_MS)
        self.setWindowOpacity(max(0.0, min(1.0, cur + step)))

    def _refresh_opacity(self, force_using: bool | None = None):
        if not self.isVisible() and force_using is None:
            return
        if force_using is None:
            # 正在使用?  -> 有焦点(正在输入) 或 鼠标正停留在这个窗口上(悬停查看)
            mouse_in = self.rect().adjusted(-6, -6, 6, 6).contains(
                self.mapFromGlobal(QCursor.pos())
            )
            using = self.isActiveWindow() or self.hasFocus() or mouse_in
        else:
            using = force_using
        opaque = using  # 窗口“正被使用”时保持不透明
        if opaque != self._is_active_opacity:
            self._is_active_opacity = opaque
            self._transition_opacity(OPACITY_ACTIVE if opaque else OPACITY_FOCUS_LOST)

    # ------------------------------------------------------------------
    # 绘制：手绘圆角半透明卡片（保障背景可见）
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 复用缓存的颜色/边框，避免每帧重建临时对象（选块拖动时显著减卡顿）
        grad = getattr(self, "_grad_brush", None)
        if grad is None:
            g = QLinearGradient(0, 0, 0, 1)
            g.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
            g.setColorAt(0, QColor(52, 53, 65, 246))
            g.setColorAt(1, QColor(27, 28, 36, 246))
            self._grad_brush = QBrush(g)
            # #2 假毛玻璃：柔和描边 + 顶部高光，深色下比纯 40-alpha 直边更有“浮层感”
            self._border_pen = QColor(255, 255, 255, 46)
            self._edge_pen = QColor(0, 0, 0, 70)       # 外缘底光（压暗描边）
            self._top_pen = QColor(255, 255, 255, 26)  # 顶部 1px 高光
            grad = self._grad_brush
        painter.setBrush(grad)
        painter.setPen(self._border_pen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), CARD_RADIUS, CARD_RADIUS)
        # 外部阴影/暗边：让卡片从深色桌面“浮”起来
        painter.setPen(self._edge_pen)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), CARD_RADIUS, CARD_RADIUS)
        painter.setPen(self._top_pen)
        # 顶部内描边高光（模拟毛玻璃的顶部受光，视觉“抬”起 1px）
        tr = self.rect().adjusted(2, 1, -2, 0)
        painter.drawLine(tr.topLeft() + QPoint(CARD_RADIUS, 1), tr.topRight() - QPoint(CARD_RADIUS, 0))
        painter.end()
        super().paintEvent(event)

    # ------------------------------------------------------------------
    # 显示/隐藏
    # ------------------------------------------------------------------
    def toggle(self):
        # 频繁开关: 用一个最小间隔合并连续触发, 避免热键连按/重复排队导致的抖动
        now = _monotonic_ms()
        if now - getattr(self, "_last_toggle_ts", 0) < 90:
            return
        self._last_toggle_ts = now
        if self.isVisible():
            self.hide_window()
        else:
            self.show_window()

    def show_window(self):
        self._center()
        self._is_active_opacity = True
        # 唤起前清空输入法组合上下文, 确保本次显示从干净输入文档开始
        try:
            im = QGuiApplication.inputMethod()
            im.commit()
            im.reset()
        except Exception:
            pass
        # 唤起浮现动画：由 0 -> 1 淡入 + 从下方 14px 微升，营造“Spotlight 浮现”感
        self.setWindowOpacity(0.0)
        self._reveal_origin = self.pos()
        self._reveal_time = _monotonic_ms()
        # 一次性完成显示+置顶+聚焦, 减少 Windows 上多次窗口管理调用
        self.show()
        self.raise_()
        self.activateWindow()
        # 启动透明度巡检器，让窗口随焦点/鼠标实时透明(失焦即透明)
        self._start_opacity_watch()
        # 启动淡入（最终目标 1.0）+ 上滑，168ms 完成
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(FADE_STEP)
        self._reveal_timer.timeout.connect(self._reveal_tick)
        self._reveal_timer.start()
        txt = self._title.text().strip()
        if self._mode == "detail":
            # 之前停在详情视图：恢复详情（不干扰已渲染内容）
            self._set_detail_size()
            self._title.setFocus(Qt.OtherFocusReason)
            return
        if txt:
            # 结果已就绪且文本没变, 不再重复搜索(避免闪烁与开销)
            if getattr(self, "_last_query", None) == txt and self._list.count():
                self._list.show()
                # 【关键修复】只要输入框仍有内容(txt 非空)就必须展开到 428px 搜索态，
                # 不能依赖 _expanded 标记。因为「Ctrl+A 全选→直接打中文」的 IME 组合
                # 输入会在中途把 text() 短暂置空 → _do_search 误触发 _collapse(), 把
                # _expanded 永久置 False、窗口收起成 76px → 中文/放大镜/列表全挤进矮框。
                # 这里用 _expand()(以是否有内容为准)强制回到展开态, 根治"窗口不展开"。
                self._expand()
            else:
                self._do_search()
        else:
            self._collapse()
            self._title.setFocus(Qt.OtherFocusReason)
        self._dump_geo("show")

    def _reveal_tick(self):
        """唤起浮现：透明度 0→1 + y 向上偏移 14px→0（线性 168ms）。"""
        el = _monotonic_ms() - getattr(self, "_reveal_time", 0)
        t = min(1.0, el / 168.0)
        self.setWindowOpacity(t)                      # 淡入
        if self._reveal_origin is not None:
            self.move(self._reveal_origin.x(),
                      self._reveal_origin.y() - int(14 * (1.0 - t)))  # 上滑
        if t >= 1.0:
            if self._reveal_timer is not None:
                self._reveal_timer.stop()
            self._reveal_timer = None
            self._refresh_opacity(force_using=True)
            self._dump_geo("reveal")

    def hide_window(self):
        self._dump_geo("pre-hide")
        # Windows 输入法「Ctrl+A 全选后直接打中文」时, 中文是否仍处在 IME 预编辑
        # (pre-edit) 组合态; 若不清理就 hide(), 下注 show() 找回焦点时会带着
        # 半提交的组合文本, 中文按被裁剪的预编辑高度重排 → 只显示上半截。
        # commit()+reset() 让预编辑上屏并清空组合上下文, 规避此问题。
        try:
            im = QGuiApplication.inputMethod()
            im.commit()
            im.reset()
        except Exception:
            pass
        self._stop_opacity_watch()
        if self._reveal_timer is not None:
            self._reveal_timer.stop()
            self._reveal_timer = None
        self.hide()

    # ------------------------------------------------------------------
    # 高度连续动画（展开/收起/进详情），替代 setFixedSize 的瞬间跳变
    # ------------------------------------------------------------------
    RESIZE_MS = 170
    def _animate_height(self, target: int):
        """从当前高度向 target 做 ~170ms 高度插值（Spotlight 式收缩过渡）。

        用「帧计数」而非墙钟推进，保证真实 14ms 定时器与测试逐帧驱动得到一致结果。
        """
        self._resize_from = self.height()
        self._resize_to = target
        self._resize_ticks = 0
        self._resize_total = max(1, int(self.RESIZE_MS / 14))
        # 动画期间放开固定尺寸约束，才能连续 resize
        self.setMinimumSize(0, 0)
        self.setMaximumSize(100000, 100000)
        if not self._resize_timer.isActive():
            self._resize_timer.start()

    def _resize_tick(self):
        self._resize_ticks += 1
        t = min(1.0, self._resize_ticks / float(self._resize_total))
        mid = int(self._resize_from + (self._resize_to - self._resize_from) * t)
        self.resize(self._win_w, max(H_COLLAPSED, mid))
        # Windows 无边框置顶窗口在 setFixedSize + resize 动画下，布局不总是即时重排，
        # 子控件(输入框/列表/详情)几何会停留在旧位置 → 中文与列表文字重叠。
        # 强制当前布局立即重新激活，保证每次动画帧后子控件跟随窗口新几何。
        self.layout().activate()
        if t >= 1.0:
            self.setFixedSize(self._win_w, self._resize_to)
            self._resize_timer.stop()
            self.layout().activate()

    def _collapse(self, animated: bool = False):
        """收起为极窄搜索条。

        逐字删除到空时优先走「瞬间收起」(animated=False)：若带高度动画，中间 resize
        会让输入框 placeholder 在局部高度内重新居中，造成“闪现到最下方又回原位”的抖动。
        瞬间收起则干净利落，placeholder 纹丝不动。展开(输入内容)仍保留平滑动画。
        """
        self._expanded = False
        self._list.hide()
        self._detail_view.hide()
        self._mode = "list"
        if animated:
            self._animate_height(H_COLLAPSED)
        else:
            if self._resize_timer.isActive():
                self._resize_timer.stop()   # 中断进行中的高度动画，避免与瞬间收起冲突
            self.setFixedSize(self._win_w, H_COLLAPSED)

    def _expand(self):
        if not self._expanded:
            self._expanded = True
            self._list.show()
            self._animate_height(H_EXPANDED)

    def _show_detail(self, key: str):
        """把窗口切换到"详情视图"：隐藏结果列表，显示内嵌详情正文。"""
        if not key:
            return
        display_key, html = self._searcher.lookup(key)
        from ui.dict_render import convert_dict_html
        try:
            if html:
                nice = convert_dict_html(html)
            else:
                nice = f"<p style='color:#8E8E93;padding:16px'>未找到该词条：{key}</p>"
        except Exception:
            nice = f"<p style='color:#8E8E93;padding:16px'>无法解析该词条：{key}</p>"
        self._detail_view.setHtml(nice)
        self._detail_view.document().setDefaultStyleSheet("")  # 已由 dict_render 内联样式
        # 左右边距：让词头/释义/句例统一缩进并与搜索结果左边缘对齐（QText 的
        # body{padding} 对左右偏移基本无效，改用 documentMargin 可靠地控制整块左边距）。
        # 实测搜索结果文字左缘≈18px（option.rect.adjusted(6)+笔画+8），取 18px 与之像素级对齐。
        self._detail_view.document().setDocumentMargin(18)
        self._current_detail_key = key
        self._mode = "detail"
        # 输入框保持用户查询词不变（返回列表时列表/联想原样恢复）
        self._list.hide()
        self._detail_view.show()
        self._detail_view.verticalScrollBar().setValue(0)
        self._animate_height(H_DETAIL)

    def _set_detail_size(self):
        self._expanded = True
        self._animate_height(H_DETAIL)

    def _back_to_list(self):
        """从详情视图返回结果列表（保留当前结果与输入词）。"""
        if self._mode != "detail":
            return
        self._mode = "list"
        self._detail_view.hide()
        self._title.setFocus(Qt.OtherFocusReason)
        if self._list.count():
            self._list.show()
            self._animate_height(H_EXPANDED)
            self._list.setCurrentRow(max(0, self._list.currentRow()))
        else:
            self._animate_height(H_COLLAPSED)

    def _center(self):
        if self._did_center or not QApplication_available():
            return
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self._win_w // 2, geo.top() + int(geo.height() * 0.15))
        self._did_center = True

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def _on_text_changed(self, _text):
        # 用户在详情视图中开始输入 → 自动切回"列表待输入"状态
        if self._mode == "detail":
            self._back_to_list()
        self._timer.start()

    def _do_search(self, _seq=0):
        q = self._title.text().strip()
        if not q:
            # 空输入(纯空格也算空)：收起且清空结果，避免回车误打开上一个词的详情
            self._last_query = ""
            self._last_rows = ()
            self._list.setCurrentItem(None)
            self._list.setCurrentRow(-1)
            self._collapse()
            return
        rows = self._searcher.search(q, MAX_SUGGEST)
        self._render_results(q, rows)

    def _render_results(self, q: str, rows):
        """把查询结果渲染进列表。只用当前文本对应的结果。"""
        cur = self._title.text().strip()
        if cur != q:  # 输入已变化，丢弃过期结果
            return
        self._last_query = q
        if tuple(rows) == getattr(self, "_last_rows", None):
            # 结果与上次完全相同(如回退到已显示过的前缀), 跳过重建,
            # 避免无谓的 clear+addItem 清掉用户当前的选中/滚动位置。
            return
        self._last_rows = tuple(rows)
        self._list.clear()
        if not rows:
            self._expand()
            # #9 空态：友好的无结果提示（禁用，不可选/不可激活）
            it = QListWidgetItem(f"没有找到 “{q}”")
            it.setData(Qt.UserRole, "")
            it.setData(Qt.UserRole + 1, "试试更少字、检查拼写，或按 Esc 关闭")
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(QSize(self._list.width() or 300, self._row_h))
            self._list.addItem(it)
            self._list.setCurrentRow(-1)
            return
        self._expand()
        for key, summary in rows:
            it = QListWidgetItem(key)
            it.setData(Qt.UserRole, key)
            it.setData(Qt.UserRole + 1, summary or "")  # 释义预览
            it.setSizeHint(QSize(self._list.width() or 300, self._row_h))
            self._list.addItem(it)
        self._list.setCurrentRow(0)

    # ------------------------------------------------------------------
    # 回车 / 选择
    # ------------------------------------------------------------------
    def _current_key(self) -> str | None:
        # 仅返回「真实词条」项（UserRole 非空）。空态提示/无选中项时返回 None，
        # 这样 Enter 不会把查不到的文本(如中文"金额")硬切进详情视图。
        item = self._list.currentItem()
        if item:
            key = item.data(Qt.UserRole)
            return key if key else None   # 空态项 UserRole='' -> 返回 None
        return None

    def _on_return(self):
        if self._mode == "detail":
            # 已在详情视图，Enter 无操作（避免重复切换）
            return
        # 空输入(没有真实查询词)时忽略回车——防止"输入空格回车却打开上一个词的详情"
        if not self._title.text().strip():
            return
        key = self._current_key()
        if not key:
            # 无真实词条（空输入 / 没有找到的占位项）：不切详情，保持现状。
            return
        self._show_detail(key)

    def _open_item(self, item):
        # 鼠标点击结果项同样进入详情视图
        self._show_detail(item.data(Qt.UserRole))

    # ------------------------------------------------------------------
    # 键盘：Esc 隐藏
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            # 详情视图：Esc 先返回结果列表；列表视图：Esc 隐藏整个窗口
            if self._mode == "detail":
                self._back_to_list()
            else:
                self.hide_window()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """拦截输入框的 →/↓/↑/Esc/Enter，实现 Spotlight 式键盘导航。

        焦点始终停在搜索框(QLineEdit)，因此选择联想列表要在这儿做，
        而不是等着 widget 自行获得键盘焦点。
        """
        if obj is self._title and event.type() == QEvent.Type.KeyPress:
            return self._handle_nav_key(event)
        return super().eventFilter(obj, event)

    def _handle_nav_key(self, event: "QKeyEvent") -> bool:
        """处理导航按键。返回 True 表示已消费。"""
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self._mode == "detail":
                self._back_to_list()
            else:
                self.hide_window()
            event.accept()
            return True
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._list.isVisible():
            n = self._list.count()
            if n <= 0:
                return False
            row = self._list.currentRow()
            if row < 0:
                row = 0
            else:
                row += 1 if key == Qt.Key.Key_Down else -1
            row = max(0, min(n - 1, row))
            self._list.setCurrentRow(row)
            event.accept()
            return True
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            # 回车打开当前选中（未选中则用输入框文本）
            self._on_return()
            event.accept()
            return True
        return False

    # ------------------------------------------------------------------
    # 透明度：由 _refresh_opacity 定时巡检决定（失焦/移出即透明，悬停/聚焦恢复）
    # ------------------------------------------------------------------
    def event(self, event):
        return super().event(event)

    def enterEvent(self, event):
        # 鼠标进入立即起动渐变恢复不透明（160ms 淡入，更跟手；不用等 150ms 巡检拍）
        if not self._is_active_opacity:
            self._is_active_opacity = True
            self._transition_opacity(OPACITY_ACTIVE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        # 移出窗口由巡检器在下一拍里判透明（不立刻跳，避免悬停边缘抖动）
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # 拖动：按住输入框旁的卡片空白 / 拖动手柄拖动
    # ------------------------------------------------------------------
    def _begin_drag(self, event):
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self._dragging = True

    def _do_drag(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return True
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 空白区域（非输入框/列表）按住可拖动
            self._begin_drag(event)
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._do_drag(event):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)


class _DragHandle(QFrame):
    """左上角/顶部拖动手柄：接受 mouse 事件转发给父窗口拖动。"""

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self.setFixedSize(40, 16)
        self.setCursor(Qt.SizeAllCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        col = QColor(255, 255, 255, 90)
        p.setPen(col)
        w = self.width()
        p.drawLine(6, 5, w - 10, 5)
        p.drawLine(6, 10, w - 10, 10)
        p.end()
        super().paintEvent(event)

    def mousePressEvent(self, e):
        self._owner._begin_drag(e)

    def mouseMoveEvent(self, e):
        if self._owner._do_drag(e):
            e.accept()

    def mouseReleaseEvent(self, e):
        self._owner._dragging = False


def _monotonic_ms() -> int:
    """单调时钟毫秒(用于合并连续事件, 不受系统时间调整影响)。"""
    import time
    return int(time.monotonic() * 1000)


def QApplication_available():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() is not None