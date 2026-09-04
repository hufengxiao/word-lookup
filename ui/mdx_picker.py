"""自绘 MDX 文件选择对话框 —— 扁平列表式，替换 QFileDialog/QFileSystemModel。

背景决策：
  * QFileDialog 原生模式在打包后 Windows 上 exec() 随机 0xC0000005 崩溃；
    DontUseNativeDialog 自绘模式又无法浏览磁盘。
  * QTreeView+QFileSystemModel 的树导航在 Windows 上体验差且不可靠(用户始终
    陷在当前目录、看不到同级目录怎么跳都出不来)。
故改用纯 QListWidget 扁平列表：当前目录里的内容按「上级入口 + 子目录 + 文件」
逐行铺开，任何一层都能一目了然看到所有子目录并可点击进入；上级永远有一行，
不可能"被困"在某一层。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


def _dirs_files(path: str, only_mdx: bool):
    """返回 (子目录列表, 文件列表)，都排序；目录在前。only_mdx 时文件只留 .mdx。"""
    sub, files = [], []
    try:
        for n in sorted(os.listdir(path)):
            p = os.path.join(path, n)
            if os.path.isdir(p):
                sub.append(n)
            elif only_mdx:
                if n.lower().endswith(".mdx"):
                    files.append(n)
            else:
                files.append(n)
    except OSError:
        pass
    return sub, files


class MdxPickerDialog(QDialog):
    """自绘 .mdx 词典选择(扁平列表, 不依赖 QFileDialog/QFileSystemModel)。

    列表每层结构：第一行「上级目录」→ 之后所有子目录(可点击进入) → 再之后文件。
    顶部：地址栏(可编辑任意路径) + 上级按钮 + 过滤下拉。
    """

    def __init__(self, start_dir: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择 MDX 词典")
        self.setModal(True)
        self.setMinimumSize(640, 460)
        self._selected_path: str | None = None
        self._only_mdx = False

        root0 = start_dir or os.path.expanduser("~")
        root0 = os.path.abspath(root0)
        if not os.path.isdir(root0):
            root0 = os.path.expanduser("~")
        self._current = root0

        # ---- 地址栏 ----
        path_row = QHBoxLayout()
        btn_up = QPushButton("\u2191 上级")
        btn_up.setToolTip("返回当前目录的上一级")
        btn_up.clicked.connect(self._go_up)
        self._path_edit = QLineEdit(self)
        self._path_edit.setText(root0)
        self._path_edit.returnPressed.connect(self._goto_path)
        btn_go = QPushButton("转到")
        btn_go.clicked.connect(self._goto_path)
        path_row.addWidget(btn_up)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(btn_go)

        # ---- 文件列表 ----
        self._list = QListWidget(self)
        self._list.itemClicked.connect(self._on_click)
        self._list.itemDoubleClicked.connect(self._on_double)

        # ---- 状态 + 过滤 ----
        info_row = QHBoxLayout()
        self._status = QLabel("未选择")
        self._status.setStyleSheet("color:#999;")
        self._filter_box = QComboBox(self)
        self._filter_box.addItems(["词性词典 (*.mdx)", "所有文件 (*)"])
        self._filter_box.currentIndexChanged.connect(self._on_filter)
        info_row.addWidget(self._status, 1)
        info_row.addWidget(QLabel("过滤:"), 0)
        info_row.addWidget(self._filter_box, 0)

        # ---- 确定/取消 ----
        buttons = QDialogButtonBox(self)
        ok_btn = buttons.addButton("选 定", QDialogButtonBox.ButtonRole.AcceptRole)
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.clicked.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(path_row)
        lay.addWidget(self._list, 1)
        lay.addLayout(info_row)
        lay.addWidget(buttons)
        self.setLayout(lay)
        self._filter_box.setCurrentIndex(1)  # 默认「所有文件」: 避免看不到任何文件; 要只看词典再切 mdx
        self._refresh()

    # ---- 目录导航 ----
    def _cwd(self) -> str:
        return self._current

    def set_root(self, path: str) -> None:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            path = os.path.dirname(path) or os.path.expanduser("~")
        self._current = path
        self._path_edit.setText(path)
        self._refresh()

    def _refresh(self) -> None:
        """按当前目录重建列表：上级入口 → 子目录 → 文件。"""
        cur = self._current
        self._list.clear()
        parent = os.path.dirname(cur)
        if parent and parent != cur and os.path.isdir(parent):
            it = QListWidgetItem(f"\u2191  上级目录 \u00b7 {os.path.basename(parent) or parent}")
            it.setForeground(Qt.GlobalColor.gray)
            f = it.font(); f.setItalic(True); it.setFont(f)
            it.setData(Qt.ItemDataRole.UserRole, ("up", parent))
            self._list.addItem(it)

        sub, files = _dirs_files(cur, self._only_mdx)
        for n in sub:
            it = QListWidgetItem("\U0001F4C1 " + n)  # 📁
            it.setData(Qt.ItemDataRole.UserRole, ("dir", os.path.join(cur, n)))
            self._list.addItem(it)
        for f in files:
            it = QListWidgetItem("   " + f)
            it.setData(Qt.ItemDataRole.UserRole, ("file", os.path.join(cur, f)))
            self._list.addItem(it)

        if not sub and not files:
            self._status.setText("此目录为空")
        else:
            self._status.setText(f"{len(sub)} 个目录 · {len(files)} 个文件    当前: {cur}")

    def _on_click(self, item: QListWidgetItem):
        kind, path = item.data(Qt.ItemDataRole.UserRole)
        if kind == "file":
            self._status.setText("文件: " + path)
            self._selected_path = path
        elif kind == "dir":
            self._status.setText("目录: " + path)

    def _on_double(self, item: QListWidgetItem):
        kind, path = item.data(Qt.ItemDataRole.UserRole)
        if kind == "dir":
            self.set_root(path)      # 双击目录进入
        elif kind == "file":
            self._on_accept()        # 双击文件直接选定
        elif kind == "up":
            self.set_root(path)

    def _go_up(self) -> None:
        parent = os.path.dirname(self._current)
        if parent and parent != self._current and os.path.isdir(parent):
            self.set_root(parent)

    def _goto_path(self) -> None:
        p = self._path_edit.text().strip().strip('"') or "~"
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isdir(p):
            self.set_root(p)
            self._status.setText("")
        else:
            self._status.setText("路径不存在或不是目录")

    def _on_filter(self, idx: int) -> None:
        self._only_mdx = (idx == 0)
        self._refresh()

    def _on_accept(self) -> None:
        if not self._selected_path or not os.path.isfile(self._selected_path):
            sub, files = self._dirs_all()
            mdx = [os.path.join(self._current, f) for f in files if f.lower().endswith(".mdx")]
            self._selected_path = mdx[0] if mdx else None
        if self._selected_path:
            self.accept()

    def _dirs_all(self):
        return _dirs_files(self._current, False)

    @property
    def selected_path(self) -> str | None:
        return self._selected_path


if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    d = MdxPickerDialog()
    if d.exec() == QDialog.Accepted:
        print("SELECTED:", d.selected_path)