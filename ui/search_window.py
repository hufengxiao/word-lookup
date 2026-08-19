# -*- coding: utf-8 -*-
"""Spotlight 风格的搜索主窗口。"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from dictionary.searcher import Searcher

# 透明状态
OPACITY_ACTIVE = 1.0      # 正常
OPACITY_FOCUS_LOST = 0.12  # 近乎透明（失焦）

MAX_SUGGEST = 20
SEARCH_DELAY_MS = 60      # 输入去抖


class SearchWindow(QFrame):
    """Spotlight 式悬浮搜索框。

    交互：
      - 输入单词即时联想（前缀搜索）
      - ↑/↓ 选择，Enter 打开详情
      - Esc 隐藏
      - 失焦 → 近乎透明；鼠标移入 → 恢复不透明
      - 鼠标按住空白处可拖动窗口
    """

    # 热键触发时由外部调用 toggle()
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
        self.setFixedSize(480, 420)
        self.setWindowOpacity(OPACITY_ACTIVE)

        # 圆角半透明卡片背景
        self.setObjectName("searchCard")
        self.setStyleSheet(
            """
            #searchCard {
                background: rgba(38, 38, 38, 235);
                border-radius: 14px;
                border: 1px solid rgba(255,255,255,60);
            }
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # 搜索输入框
        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("输入英文单词查询…")
        self._edit.setFont(QFont("Segoe UI", 15))
        self._edit.setStyleSheet(
            """
            QLineEdit {
                background: transparent; color: #f2f2f2;
                border: none; font-size: 18px; selection-background-color:#3b82f6;
            }
            """
        )
        self._edit.textChanged.connect(self._on_text_changed)
        self._edit.returnPressed.connect(self._on_return)
        self._edit.setFocusPolicy(Qt.StrongFocus)

        # 结果列表
        self._list = QListWidget(self)
        self._list.setStyleSheet(
            """
            QListWidget {
                background: transparent; color: #e8e8e8;
                border: none; outline: none; font-size: 14px;
            }
            QListWidget::item { padding: 6px 10px; border-radius: 6px; }
            QListWidget::item:selected {
                background: rgba(59,130,246,120); color: white; border-radius: 6px;
            }
            """
        )
        self._list.hide()
        self._list.itemActivated.connect(self._open_item)

        lay.addWidget(self._edit)
        lay.addWidget(self._list, 1)

        # 输入去抖定时器
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DELAY_MS)
        self._timer.timeout.connect(self._do_search)

        self._is_active_opacity = True
        self._did_center = False

    # ------------------------------------------------------------------
    # 默认详情窗口工厂
    # ------------------------------------------------------------------
    def _default_detail(self, parent=None):
        from ui.detail_window import DetailWindow
        return DetailWindow(parent)

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
        self._edit.setFocus(Qt.OtherFocusReason)
        # 若上次有词条，保留以便快速重查
        if self._edit.text().strip():
            self._do_search()

    def hide_window(self):
        self.hide()

    def _center(self):
        """把窗口放到主屏上部（Spotlight 大约在 1/4 高度）。"""
        if self._did_center or not QApplication_available():
            return
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = geo.center().x() - self.width() // 2
            y = geo.top() + int(geo.height() * 0.18)
            self.move(x, y)
        self._did_center = True

    # ------------------------------------------------------------------
    # 搜索逻辑
    # ------------------------------------------------------------------
    def _on_text_changed(self, _text):
        self._timer.start()

    def _do_search(self):
        q = self._edit.text().strip()
        self._list.clear()
        if not q:
            self._list.hide()
            # 无输入时展示常用词（可选，展示几个高频词作为引导）
            self._show_empty_hint()
            return
        rows = self._searcher.search(q, MAX_SUGGEST)
        if not rows:
            self._list.hide()
            self._show_empty_hint("无匹配结果")
            return
        for key, _kl in rows:
            it = QListWidgetItem(key)
            it.setData(Qt.UserRole, key)
            self._list.addItem(it)
        self._list.setCurrentRow(0)
        self._list.show()

    def _show_empty_hint(self, text="输入字母开始搜索…"):
        # 不向用户列表塞占位项，仅提示
        pass

    # ------------------------------------------------------------------
    # 回车 / 选择
    # ------------------------------------------------------------------
    def _current_key(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else (
            self._edit.text().strip() if self._edit.text().strip() else None
        )

    def _on_return(self):
        key = self._current_key()
        if not key:
            return
        self._open_word(key)

    def _open_item(self, item):
        key = item.data(Qt.UserRole)
        if key:
            self._open_word(key)

    def _open_word(self, key: str):
        html = self._searcher.lookup(key)
        detail = self._detail_factory()
        detail.set_html(key, html if html else "<p style='color:#888'>未找到该词条。</p>")
        # 详情窗口靠近搜索窗
        geo = self.geometry()
        detail.move(geo.right() + 12, geo.top())
        detail.show()
        detail.raise_()

    # ------------------------------------------------------------------
    # 键盘事件（上下键交给 QListWidget，这里补 Esc）
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self.hide_window()
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # 透明度交互：失焦变透明，鼠标移入恢复
    # ------------------------------------------------------------------
    def changeEvent(self, event):
        if event.type() == Qt.Type.WindowStateChange:
            super().changeEvent(event)
    def event(self, event):
        etype = event.type()
        if etype == Qt.Event.WindowDeactivate:
            # 失焦 → 近乎透明
            self._is_active_opacity = False
            self.setWindowOpacity(OPACITY_FOCUS_LOST)
        elif etype in (Qt.Event.Enter, Qt.Event.FocusIn):
            if not self._is_active_opacity:
                self._is_active_opacity = True
                self.setWindowOpacity(OPACITY_ACTIVE)
        elif etype == Qt.Event.WindowActivate:
            self._is_active_opacity = True
            self.setWindowOpacity(OPACITY_ACTIVE)
        return super().event(event)

    def enterEvent(self, event):
        if not self._is_active_opacity:
            self._is_active_opacity = True
            self.setWindowOpacity(OPACITY_ACTIVE)
            self.activateWindow()
            self._edit.setFocus(Qt.OtherFocusReason)
        super().enterEvent(event)

    # ------------------------------------------------------------------
    # 拖动（鼠标按住窗口空白 / 输入框顶部区域）
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragging = True
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_dragging", False) and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)


def QApplication_available():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() is not None