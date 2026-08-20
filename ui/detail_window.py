# -*- coding: utf-8 -*-
"""词条详情窗口：渲染词典正文 HTML（轻量 QTextBrowser）。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

_DEFAULT_STYLE = """
QTextBrowser {
    background: #F4F5F7;
    border: none;
    selection-background-color: #0A84FF;
    selection-color: #ffffff;
}
QScrollBar:vertical { width: 10px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: #C9CBD1; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #A9ABB3; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


class DetailWindow(QWidget):
    """显示一个词条完整内容的窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("查词")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
            | Qt.WindowStaysOnTopHint
        )
        self.resize(640, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 标题栏（苹果风深色工具栏）
        self._title = QLabel("")
        self._title.setObjectName("detailTitle")
        self._title.setStyleSheet(
            "QLabel#detailTitle { padding: 8px 14px; font-size: 14px;"
            " font-weight: 600; color: #F5F5F7; background-color: transparent; }"
        )
        # 关闭按钮（用 QPushButton + clicked 信号，避免覆盖事件处理的坑）
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(
            "QPushButton { border:none; color:#A1A1A6; font-size:13px;"
            " border-radius:13px; background:transparent; }"
            "QPushButton:hover { background:rgba(255,255,255,28); color:#FFFFFF; }"
        )
        self._close_btn.clicked.connect(self.close)

        title_row = QHBoxLayout()
        title_row.addWidget(self._title, 1)
        title_row.addWidget(self._close_btn, 0)
        title_row.setContentsMargins(0, 0, 0, 0)
        self._title_bar = QWidget()
        self._title_bar.setLayout(title_row)
        self._title_bar.setStyleSheet("background: #2C2C2E;")

        # 正文
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setStyleSheet(_DEFAULT_STYLE)
        # 设置可读的等宽/衬线字体
        self._base_font = QFont()
        self._base_font.setPointSize(11)
        self._browser.setFont(self._base_font)

        root.addWidget(self._title_bar)
        root.addWidget(self._browser, 1)

    # ------------------------------------------------------------------
    def set_word(self, word: str):
        self._title.setText(word)
        self.setWindowTitle(word)

    def set_html(self, word: str, html: str):
        self.set_word(word)
        if not html:
            self._browser.setHtml(f"<div style='font:15px sans-serif;padding:20px'>未找到：{word}</div>")
            return
        # 已由 dict_render 处理过的干净排版本(含 <style>) 直接渲染
        if "<style>" in html or "<body" in html and "<!DOCTYPE" in html:
            self._browser.setHtml(html)
            return
        cleaned = self._clean_html(html)
        # QTextBrowser 不加载外链 css，注入一份可读基础样式，避免挤成一团
        base_css = (
            "body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;font-size:15.5px;"
            "line-height:1.7;color:#1D1D1F;padding:24px 30px;background:#F4F5F7;}"
            "h1,h2,h3{color:#111114;}"
            "h1{font-size:30px;margin:2px 0 8px;}"
            "h2{font-size:19px;margin:16px 0 6px;color:#333;}"
            "h3{font-size:16px;margin:12px 0 4px;}"
            ".phon,span{color:#6E6E73;} .pos{color:#0A84FF;font-style:italic;}"
            "table{border-collapse:collapse;} td,th{padding:3px 10px;}"
            "ol,ul{margin:4px 0 8px;} li{margin:3px 0;}"
            "img{max-width:100%;}"
        )
        self._browser.document().setDefaultStyleSheet(base_css)
        self._browser.setHtml(cleaned)

    @staticmethod
    def _clean_html(html: str) -> str:
        """从词典 HTML 中剔除 <link>/<script> 及外链引用，便于 QTextBrowser 渲染。"""
        import re

        # 删除 <link ...> 与 <script ...>...</script>
        html = re.sub(r"<link\b[^>]*>", "", html, flags=re.I)
        html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
        # 删除 <style>...</style>
        html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.I | re.S)
        # 删除内联事件属性（onclick 等）
        html = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
        # 删除音频/视频引用
        html = re.sub(r"<audio\b[^>]*>.*?</audio>", "", html, flags=re.I | re.S)
        # 保留 <img>，但因无 mdd 资源，外链图会缺失——保留 onerror 兜底由浏览器忽略
        return html

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_M):
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)