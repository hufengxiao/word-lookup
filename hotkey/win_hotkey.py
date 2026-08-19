"""
Windows 全局热键支持。

通过 Win32 API `RegisterHotKey` 注册系统级热键，不依赖第三方包。
在新线程中运行消息循环，热键按下时调用 `callback`。

用例（Shift+Ctrl+M）:
    from .win_hotkey import GlobalHotkey
    gh = GlobalHotkey(mods=("SHIFT", "CTRL"), key="M")
    gh.on_press = my_callback
    gh.start()
    # 结束时 gh.close()

Linux/macOS 上该模块会给出提示（本项目主要面向 Windows）。
"""
import ctypes
import ctypes.wintypes as wt
import threading

# Win32 常量
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

WM_HOTKEY = 0x0312

_MOD_MAP = {
    "ALT": MOD_ALT,
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN,
}


def _vk_from_char(ch):
    """把单个字符映射到虚拟键码（字母 A-Z 用 ASCII）。"""
    if len(ch) != 1:
        raise ValueError("按键需为单个字符")
    c = ch.upper()
    # 字母 A-Z
    if "A" <= c <= "Z":
        return ord(c)
    # 数字
    if "0" <= c <= "9":
        return ord(c)
    # 常用功能键
    special = {
        "ESC": 0x1B, "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
        "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78,
        "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
        "SPACE": 0x20, "TAB": 0x09, "BACK": 0x08, "ENTER": 0x0D,
        "DELETE": 0x2E, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
        "LEFT": 0x25, "RIGHT": 0x27, "UP": 0x26, "DOWN": 0x28,
    }
    return special.get(c)


class GlobalHotkey:
    """
    注册一个全局热键。

    :param mods: 修饰键列表，如 ["CTRL", "SHIFT"]
    :param key:  主键字符或虚拟键码，如 "M"
    :param id_:  热键 ID（自定）
    """

    def __init__(self, mods, key, id_=1):
        self.mods = mods
        self.key = key
        self.id = id_
        self.on_press = None  # 热键触发回调，无参数
        self._thread = None
        self._running = False
        self._hwnd = None

    def _mod_flags(self) -> int:
        flags = 0
        for m in self.mods:
            m = m.upper()
            if m not in _MOD_MAP:
                raise ValueError(f"不支持的修饰键: {m}")
            flags |= _MOD_MAP[m]
        return flags

    def start(self):
        """在新线程启动热键监听。"""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        # 注册热键
        vk = _vk_from_char(self.key)
        if vk is None:
            raise ValueError(f"无法解析按键: {self.key}")
        ok = user32.RegisterHotKey(None, self.id, self._mod_flags(), vk)
        if not ok:
            error = ctypes.get_last_error()
            raise RuntimeError(f"RegisterHotKey 失败，错误码 {error}（可能热键已被占用）")

        msg = wt.MSG()
        try:
            while self._running:
                # PeekMessage 非阻塞轮询 + sleep，避免完全占用线程占用资源
                r = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001)  # PM_REMOVE
                if r:
                    if msg.message == WM_HOTKEY and msg.wParam == self.id:
                        cb = self.on_press
                        if cb:
                            cb()
                    else:
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    threading.Event().wait(0.03)
        finally:
            user32.UnregisterHotKey(None, self.id)

    def close(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)


if __name__ == "__main__":
    print("热键测试: 按 Ctrl+Shift+M")
    gh = GlobalHotkey(["CTRL", "SHIFT"], "M")
    gh.on_press = lambda: print(">>> 热键触发!")
    gh.start()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gh.close()