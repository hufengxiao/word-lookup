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
from PySide6.QtCore import Qt, QTimer, QEvent, QRect
from PySide6.QtGui import (
    QFont, QPainter, QColor, QKeyEvent, QLinearGradient, QBrush,
)
from PySide6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout,
    QStyledItemDelegate,
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


class _ResultDelegate(QStyledItemDelegate):
    """Spotlight 式结果行：词头加粗醒目 + 右侧紧跟灰色释义预览。

    单词用大字、亮白(选中时)，释义用较暗的灰/浅青色并在空间不足时省略。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_font = QFont("Segoe UI", 15, QFont.Bold)
        self._sum_font = QFont("Segoe UI", 13)
        self._key_len = 0

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        base.setWidth(max(base.width(), 320))
        base.setHeight(max(base.height(), 42))
        return base

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # 选中背景 (圆角)
        if selected:
            painter.setBrush(QColor(59, 130, 246, 255))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(r, 9, 9)
        else:
            painter.setPen(Qt.NoPen)

        key = index.data(Qt.DisplayRole) or (index.data(Qt.UserRole) or "")
        summ = index.data(Qt.UserRole + 1) or ""

        # 词头文字颜色
        kc = QColor("#ffffff") if selected else QColor("#ebe9ff")
        # 释义颜色: 选中时白(半透明)，未选中时浅金色以便文字中英文混杂时醒目
        sum_color = (
            QColor(255, 255, 255, 200) if selected else QColor("#ffd98a")
        )

        # 文本基线
        painter.setFont(self._key_font)
        kx = r.left() + 8
        km = painter.fontMetrics().horizontalAdvance(key) + 8
        painter.setPen(kc)
        painter.drawText(QRect(kx, r.top(), km, r.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, key)

        # 释义（紧跟词后，剩余空间不够则省略）
        if summ:
            painter.setFont(self._sum_font)
            painter.setPen(sum_color)
            avail = r.right() - (kx + km) - 4
            avail = max(avail, 0)
            elide = painter.fontMetrics().elidedText(summ, Qt.ElideRight, avail)
            painter.drawText(QRect(kx + km, r.top(), avail, r.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, elide)
        painter.restore()


class SearchWindow(QFrame):
    """Spotlight 式悬浮搜索框。"""

    def __init__(self, searcher: Searcher, detail_factory=None, parent=None):
        super().__init__(parent)
        self._searcher = searcher
        self._detail_factory = detail_factory or self._default_detail

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

    # ------------------------------------------------------------------
    # 默认详情窗口工厂
    # ------------------------------------------------------------------
    def _default_detail(self, parent=None):
        from ui.detail_window import DetailWindow
        return DetailWindow(parent)

    # ------------------------------------------------------------------
    # 绘制：手绘圆角半透明卡片（保障背景可见）
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = QLinearGradient(0, 0, 0, self.height())
        r.setColorAt(0, QColor(52, 53, 65, 246))
        r.setColorAt(1, QColor(27, 28, 36, 246))
        painter.setBrush(QBrush(r))
        painter.setPen(QColor(255, 255, 255, 40))
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
        self.setWindowOpacity(OPACITY_ACTIVE)
        # 一次性完成显示+置顶+聚焦, 减少 Windows 上多次窗口管理调用
        self.show()
        self.raise_()
        self.activateWindow()
        self._title.setFocus(Qt.OtherFocusReason)
        txt = self._title.text().strip()
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
        self.hide()

    def _collapse(self):
        self._expanded = False
        self._list.hide()
        self.setFixedSize(W, H_COLLAPSED)

    def _expand(self):
        if not self._expanded:
            self._expanded = True
            self.setFixedSize(W, H_EXPANDED)
            self._list.show()

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
        self._open_word(self._current_key())

    def _open_item(self, item):
        self._open_word(item.data(Qt.UserRole))

    def _open_word(self, key: str, detail: "DetailWindow | None" = None):
        if not key:
            return
        display_key, html = self._searcher.lookup(key)
        if detail is None:
            detail = self._detail_factory()
        if html:
            try:
                from ui.dict_render import convert_dict_html
                nice = convert_dict_html(html)
                detail.set_html(display_key or key, nice)
            except Exception:
                detail.set_html(display_key or key,
                                f"<p style='color:#888'>无法解析该词条：{key}</p>")
        else:
            detail.set_html(display_key or key,
                            f"<p style='color:#888'>未找到该词条：{key}</p>")
        self._place_detail(detail)
        detail.show()
        detail.raise_()
        detail.activateWindow()
        # 持有引用，避免局部变量被回收导致窗口消失
        if not hasattr(self, "_details"):
            self._details = []
        self._details.append(detail)

    def _place_detail(self, detail):
        """把详情窗口放到搜索窗右侧；若会越界则放到下方（都在屏内）。"""
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        sr = screen.availableGeometry() if screen else None
        g = self.geometry()
        x = g.right() + 14
        y = g.top()
        dw = detail.width()
        if sr and x + dw > sr.right() + 10:
            x = max(sr.left(), sr.right() - dw - 10)  # 太靠右就挪回屏内
            y = min(y, sr.bottom() - detail.height())
        detail.move(x, max(0, y))

    # ------------------------------------------------------------------
    # 键盘：Esc 隐藏
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
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
    # 透明度：失焦变透明，鼠标移入恢复
    # ------------------------------------------------------------------
    def event(self, event):
        etype = event.type()
        if etype == QEvent.Type.WindowDeactivate:
            if self._is_active_opacity:
                self._is_active_opacity = False
                self.setWindowOpacity(OPACITY_FOCUS_LOST)
        elif etype == QEvent.Type.WindowActivate:
            self._is_active_opacity = True
            self.setWindowOpacity(OPACITY_ACTIVE)
        elif etype == QEvent.Type.Enter:
            if not self._is_active_opacity:
                self._is_active_opacity = True
                self.setWindowOpacity(OPACITY_ACTIVE)
                self.activateWindow()
                self._title.setFocus(Qt.FocusReason.OtherFocusReason)
        return super().event(event)

    def enterEvent(self, event):
        if not self._is_active_opacity:
            self._is_active_opacity = True
            self.setWindowOpacity(OPACITY_ACTIVE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        # 移出窗口但未点别处时不立刻变透明（避免误触）；仅失焦时透明
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