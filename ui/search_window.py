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
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont, QPainter, QColor, QKeyEvent, QLinearGradient, QBrush
from PySide6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QHBoxLayout,
)

from dictionary.searcher import Searcher

# 透明状态
OPACITY_ACTIVE = 1.0      # 正常（唤起/鼠标移入）
OPACITY_FOCUS_LOST = 0.10  # 近乎透明（失焦）

MAX_SUGGEST = 20
SEARCH_DELAY_MS = 60      # 输入去抖
CARD_RADIUS = 14
W, H_COLLAPSED = 520, 68   # 长条搜索框尺寸（收起/唤起时）
H_EXPANDED = 420           # 输入后有结果时展开高度


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
        top.addWidget(self._title, 1)

        # 底部拖动手柄（三条杠），也可直接拖；同时是一个可见的拖动把手
        from PySide6.QtWidgets import QLabel
        self._drag_label = _DragHandle(self)

        top.addStretch(0)
        top.addWidget(self._drag_label, 0, Qt.AlignVCenter)
        lay.addLayout(top)

        # ---- 结果列表 ----
        self._list = QListWidget(self)
        self._list.setStyleSheet(
            "QListWidget { background: transparent; color: #e8e8e8;"
            " border: none; outline: none; font-size: 15px; }"
            "QListWidget::item { padding: 7px 14px; margin: 0 8px;}"
            "QListWidget::item:selected { background: #3b82f6;"
            " color: white; border-radius: 8px; }"
        )
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
        if self.isVisible():
            self.hide_window()
        else:
            self.show_window()

    def show_window(self):
        self._center()
        self.setWindowOpacity(OPACITY_ACTIVE)
        self.show()
        self.raise_()
        self.activateWindow()
        self._title.setFocus(Qt.OtherFocusReason)
        # 有词条时展示结果，否则收起成长条
        txt = self._title.text().strip()
        if txt:
            self._do_search()
        else:
            self._collapse()

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

    def _do_search(self):
        q = self._title.text().strip()
        self._list.clear()
        if not q:
            self._collapse()
            return
        rows = self._searcher.search(q, MAX_SUGGEST)
        if not rows:
            self._list.clear()
            self._expand()
            it = QListWidgetItem("无匹配结果")
            it.setFlags(Qt.NoItemFlags)
            self._list.addItem(it)
            self._list.show()
            return
        self._expand()
        for key, _kl in rows:
            it = QListWidgetItem(key)
            it.setData(Qt.UserRole, key)
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

    def _open_word(self, key: str):
        if not key:
            return
        html = self._searcher.lookup(key)
        detail = self._detail_factory()
        detail.set_html(key, html if html else
                        f"<p style='color:#888'>未找到该词条：{key}</p>")
        self._place_detail(detail)
        detail.show()
        detail.raise_()
        detail.activateWindow()

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


def QApplication_available():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() is not None