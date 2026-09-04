"""自绘 MDX 文件选择对话框 —— 替代 QFileDialog。

背景(v0.8.2/0.8.3 实机定位)：
  * QFileDialog 原生模式在 PyInstaller 打包的 Windows 上, exec() 期间会随机爆
    0xC0000005 (ACCESS_VIOLATION), 且 setOption 也救不了 — 原生对话框 exec
    底层走 Windows Shell/COM, 在部分机器不稳定。
  * QFileDialog 自绘模式(DontUseNativeDialog=True) 稳定, 但在 Windows 上无法
    正常浏览磁盘(只能待 exe 目录、目录里的 .mdx 也看不到)。
结论: 弃用 QFileDialog, 用纯 QWidget 做一个文件浏览器 — 路径栏 + QFileSystemModel
    QTreeView, 能正向浏览任意目录、双击入子目录、上级返回、过滤文件, 全程不碰
    原生 Shell/COM 对话框, 既稳定又能浏览整个磁盘。
"""
import os

from PySide6.QtCore import QDir, QModelIndex
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
)

_MDX_FILTER = ["*.mdx"]


class MdxPickerDialog(QDialog):
    """自绘 .mdx 词典选择对话框(不依赖 QFileDialog, 不碰原生 Shell)。

    布局: 地址栏(上级/路径编辑/转到) + 文件系统树(QTreeView) + 过滤 + 确定/取消。
    """

    def __init__(self, start_dir: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择 MDX 词典")
        self.setModal(True)
        self.setMinimumSize(620, 440)
        self._selected_path: str | None = None

        self._model = QFileSystemModel(self)
        self._model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self._model.setReadOnly(True)
        self._model.setNameFilters(_MDX_FILTER)  # 默认只看 .mdx(目录始终显示)

        root0 = start_dir or os.path.expanduser("~")
        root0 = root0 if os.path.isdir(root0) else os.path.expanduser("~")
        self._model.setRootPath(root0)

        # ---- 文件树 ----
        self._tree = QTreeView(self)
        self._tree.setModel(self._model)
        self._tree.setRootIsDecorated(True)
        self._tree.setAnimated(False)
        self._tree.setHeaderHidden(True)  # 单列, 只显名称
        self._tree.doubleClicked.connect(self._on_double)
        self._tree.clicked.connect(self._on_click)

        # ---- 地址栏 ----
        path_row = QHBoxLayout()
        btn_up = QPushButton("\u2191 上级")
        btn_up.setToolTip("跳转到当前目录的上一级")
        btn_up.clicked.connect(self._go_up)
        self._path_edit = QLineEdit(self)
        self._path_edit.setText(os.path.abspath(root0))
        self._path_edit.returnPressed.connect(self._goto_path)
        btn_go = QPushButton("转到")
        btn_go.clicked.connect(self._goto_path)
        path_row.addWidget(btn_up)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(btn_go)

        # ---- 状态 + 过滤行 ----
        info_row = QHBoxLayout()
        self._status = QLabel("未选择")
        self._status.setStyleSheet("color:#999;")
        self._filter_box = QComboBox(self)
        self._filter_box.addItems(["词性词典 (*.mdx)", "所有文件 (*)"])
        self._filter_box.currentIndexChanged.connect(self._apply_filter)
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
        lay.addWidget(self._tree, 1)
        lay.addLayout(info_row)
        lay.addWidget(buttons)
        self.setLayout(lay)
        self.set_root(root0)  # 建好 _path_edit 后再设初始目录
        self._apply_filter(0)

    # ---- 路径导航 ----
    def _cwd(self) -> str:
        return self._model.filePath(self._tree.rootIndex())

    def set_root(self, path: str) -> None:
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            path = os.path.dirname(path)
        idx = self._model.index(path)
        self._tree.setRootIndex(idx)
        self._path_edit.setText(self._model.filePath(idx))

    def _goto_path(self) -> None:
        p = self._path_edit.text().strip().strip('"') or "~"
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isdir(p):
            self.set_root(p)
            self._status.setText("")
        else:
            self._status.setText("路径不存在或不是目录")

    def _go_up(self) -> None:
        parent = os.path.dirname(self._cwd())
        if parent and parent != self._cwd() and os.path.isdir(parent):
            self.set_root(parent)

    def _apply_filter(self, idx: int) -> None:
        self._model.setNameFilters(_MDX_FILTER if idx == 0 else [])

    def _on_click(self, index: QModelIndex) -> None:
        fp = self._model.filePath(index)
        if self._model.isDir(index):
            self._status.setText("目录: " + fp)
        else:
            self._status.setText("文件: " + fp)
            self._selected_path = fp

    def _on_double(self, index: QModelIndex) -> None:
        fp = self._model.filePath(index)
        if self._model.isDir(index):
            self.set_root(fp)
        else:
            self._on_click(index)

    def _on_accept(self) -> None:
        # 未明确点文件(空白处确认)就选当前目录第一个 .mdx
        if not self._selected_path or not os.path.isfile(self._selected_path):
            cur = self._cwd()
            try:
                mdx = [f for f in os.listdir(cur) if f.lower().endswith(".mdx")]
            except OSError:
                mdx = []
            self._selected_path = os.path.join(cur, mdx[0]) if mdx else None
        if self._selected_path:
            self.accept()

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