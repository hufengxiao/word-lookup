# -*- coding: utf-8 -*-
"""Spotlight 风格的搜索主窗口。

交互（对齐 macOS Spotlight）：
  - 唤起即见一个长条搜索框；输入后下方展开结果列表
  - ↑/↓ 选择 · Enter 打开详情 · Esc 隐藏
  - 失焦 → 近乎透明；鼠标移入 → 恢复不透明
  - 按住输入框旁的空白/底栏可拖动窗口

背景用 QPainter 手绘（不依赖样式表 rgba 背景映射），确保卡片底色在
Windows + 无边框置顶窗口下稳定可见。
"""
from PySide6.QtCore import Qt, QTimer, QEvent, QRect, QSize
from PySide6.QtGui import (
    QFont, QPainter, QColor, QKeyEvent, QLinearGradient, QBrush, QCursor,
)
from PySide6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout,
    QStyledItemDelegate, QTextBrowser,
)
from PySide6.QtWidgets import QStyle

from dictionary.searcher import Searcher

# 透明状态
OPACITY_ACTIVE = 1.0      # 正常（唤起/鼠标移入）
OPACITY_FOCUS_LOST = 0.10  # 近乎透明（失焦）

MAX_SUGGEST = 20
SEARCH_DELAY_MS = 60      # 输入去抖
CARD_RADIUS = 14
W, H_COLLAPSED = 520, 68   # 长条搜索框尺寸（收起/唤起时）
H_EXPANDED = 420           # 输入后有结果时展开高度
H_DETAIL = 660             # 按 Enter 进入"详情视图"时的窗口高度


class _ResultDelegate(QStyledItemDelegate):
    """Spotlight 式结果行：词头加粗醒目 + 右侧紧跟灰色释义预览。

    单词用大字、亮白(选中时)，释义用较暗的灰/浅青色并在空间不足时省略。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_font = QFont("Segoe UI", 15, QFont.Bold)
        self._sum_font = QFont("Segoe UI", 13)
        # 预建颜色(避免每帧重建字符串颜色的开销)
        self._bg_on = QColor(59, 130, 246, 255)
        self._key_on = QColor("#ffffff")
        self._key_off = QColor("#ebe9ff")
        self._sum_on = QColor(255, 255, 255, 200)
        self._sum_off = QColor("#ffd98a")

    def sizeHint(self, option, index):
        w = max(option.rect.width(), 320)
        return QSize(max(w, 320), 42)

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

        kc = self._key_on if selected else self._key_off
        sum_color = self._sum_on if selected else self._sum_off

        # 词头
        painter.setFont(self._key_font)
        kx = r.left() + 8
        km = painter.fontMetrics().horizontalAdvance(key) + 8
        painter.setPen(kc)
        painter.drawText(QRect(kx, r.top(), km, r.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, key)

        # 释义
        if summ:
            painter.setFont(self._sum_font)
            painter.setPen(sum_color)
            avail = r.right() - (kx + km) - 4
            if avail > 0:
                elide = painter.fontMetrics().elidedText(summ, Qt.ElideRight, avail)
                painter.drawText(QRect(kx + km, r.top(), avail, r.height()),
                                 Qt.AlignLeft | Qt.AlignVCenter, elide)


class SearchWindow(QFrame):
    """Spotlight 式悬浮搜索框。"""

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
        self.setFixedSize(W, H_COLLAPSED)
        self.setWindowOpacity(OPACITY_ACTIVE)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        # ---- 顶部：搜索行（Spotlight 长条核心）----
        top = QHBoxLayout()
        top.setContentsMargins(16, 12, 12, 12)
        top.setSpacing(0)
        self._title = QLineEdit(self)
        self._title.setPlaceholderText("🔍  输入英文单词查询…")
        self._title.setFont(QFont("Segoe UI", 19))
        self._title.setStyleSheet(
            "QLineEdit { background: transparent; color: #ffffff;"
            " border: none; selection-background-color:#3b82f6; }"
        )
        self._title.textChanged.connect(self._on_text_changed)
        self._title.returnPressed.connect(self._on_return)
        self._title.setFocusPolicy(Qt.StrongFocus)
        # 拦截 ↑/↓/Esc/Enter，实现 Spotlight 式键盘导航（焦点一直在输入框）
        self._title.installEventFilter(self)
        top.addWidget(self._title, 1)

        # 底部拖动手柄（三条杠），也可直接拖；同时是一个可见的拖动把手
        from PySide6.QtWidgets import QLabel
        self._drag_label = _DragHandle(self)

        top.addStretch(0)
        top.addWidget(self._drag_label, 0, Qt.AlignVCenter)
        lay.addLayout(top)

        # ---- 结果列表 ----
        self._list = QListWidget(self)
        self._list.setItemDelegate(_ResultDelegate(self._list))
        self._list.setStyleSheet(
            "QListWidget { background: transparent; color: #e8e8e8;"
            " border: none; outline: none; font-size: 15px; }"
            "QListWidget::item { margin: 0 8px; }"
        )
        self._list.setSpacing(1)
        self._list.hide()
        self._list.itemActivated.connect(self._open_item)
        lay.addWidget(self._list, 1)

        # ---- 内嵌详情视图：按 Enter 后从"结果列表"切换成"详情"（同一窗口内）----
        self._detail_view = QTextBrowser(self)
        self._detail_view.setStyleSheet(
            "QTextBrowser { background: #F4F5F7; border: none;"
            " selection-background-color: #0A84FF; selection-color: #ffffff; }"
            "QScrollBar:vertical { width: 8px; background: transparent;}"
            "QScrollBar::handle:vertical { background: #C9CBD1; min-height: 30px; border-radius:4px;}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
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
            self.setWindowOpacity(OPACITY_ACTIVE if opaque else OPACITY_FOCUS_LOST)

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
            self._border_pen = QColor(255, 255, 255, 40)
            grad = self._grad_brush
        painter.setBrush(grad)
        painter.setPen(self._border_pen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), CARD_RADIUS, CARD_RADIUS)
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
        self.setWindowOpacity(OPACITY_ACTIVE)
        # 一次性完成显示+置顶+聚焦, 减少 Windows 上多次窗口管理调用
        self.show()
        self.raise_()
        self.activateWindow()
        # 启动透明度巡检器，让窗口随焦点/鼠标实时透明(失焦即透明)
        self._start_opacity_watch()
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
                self.setFixedSize(W, H_EXPANDED if self._expanded else H_COLLAPSED)
            else:
                self._do_search()
        else:
            self._collapse()
            self._title.setFocus(Qt.OtherFocusReason)

    def hide_window(self):
        self._stop_opacity_watch()
        self.hide()

    def _collapse(self):
        self._expanded = False
        self._list.hide()
        self._detail_view.hide()
        self._mode = "list"
        self.setFixedSize(W, H_COLLAPSED)

    def _expand(self):
        if not self._expanded:
            self._expanded = True
            self.setFixedSize(W, H_EXPANDED)
            self._list.show()

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
        self._current_detail_key = key
        self._mode = "detail"
        # 输入框保持用户查询词不变（返回列表时列表/联想原样恢复）
        self._list.hide()
        self._detail_view.show()
        self._detail_view.verticalScrollBar().setValue(0)
        self.setFixedSize(W, H_DETAIL)

    def _set_detail_size(self):
        self._expanded = True
        self.setFixedSize(W, H_DETAIL)

    def _back_to_list(self):
        """从详情视图返回结果列表（保留当前结果与输入词）。"""
        if self._mode != "detail":
            return
        self._mode = "list"
        self._detail_view.hide()
        self._title.setFocus(Qt.OtherFocusReason)
        if self._list.count():
            self._list.show()
            self.setFixedSize(W, H_EXPANDED)
            self._list.setCurrentRow(max(0, self._list.currentRow()))
        else:
            self.setFixedSize(W, H_COLLAPSED)

    def _center(self):
        if self._did_center or not QApplication_available():
            return
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - W // 2, geo.top() + int(geo.height() * 0.15))
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
        self._list.clear()
        if not rows:
            self._expand()
            it = QListWidgetItem("无匹配结果")
            it.setFlags(Qt.NoItemFlags)  # 占位项: 不可选/不可激活
            self._list.addItem(it)
            self._list.setCurrentRow(-1)
            return
        self._expand()
        for key, summary in rows:
            it = QListWidgetItem(key)
            it.setData(Qt.UserRole, key)
            it.setData(Qt.UserRole + 1, summary or "")  # 释义预览
            self._list.addItem(it)
        self._list.setCurrentRow(0)

    # ------------------------------------------------------------------
    # 回车 / 选择
    # ------------------------------------------------------------------
    def _current_key(self) -> str | None:
        item = self._list.currentItem()
        if item:
            return item.data(Qt.UserRole)
        return self._title.text().strip() or None

    def _on_return(self):
        if self._mode == "detail":
            # 已在详情视图，Enter 无操作（避免重复切换）
            return
        self._show_detail(self._current_key())

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
        # 鼠标进入立即恢复不透明（不用等 150ms 巡检拍），体验更跟手
        if not self._is_active_opacity:
            self._is_active_opacity = True
            self.setWindowOpacity(OPACITY_ACTIVE)
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