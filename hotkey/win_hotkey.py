"""
全局热键：基于 Qt QAbstractNativeEventFilter 拦截 WM_HOTKEY。

原理：
  在应用主线程调用 user32.RegisterHotKey(NULL, id, mods, vk)。
  hWnd 传 NULL 时，WM_HOTKEY 会投递到调用线程（即 Qt 主线程）的消息队列，
  Qt 会把该 Windows 原生消息交给 QAbstractNativeEventFilter，从而在主线程
  直接触发回调——完全避免“从独立线程跨线程发 Qt 信号”带来的时序/亲和性问题。

可靠性：
  - 主线程处理，无跨线程切换。
  - RegisterHotKey 返回 FALSE 时立即抛错（多数是热键被占用）。
  - 仅 Windows 可用；其他平台占位（本项目主要面向 Windows）。
"""
import ctypes
import ctypes.wintypes as wt

from PySide6.QtCore import QAbstractNativeEventFilter

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

_MOD_MAP = {
    "ALT": MOD_ALT, "CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
    "SHIFT": MOD_SHIFT, "WIN": MOD_WIN,
}


def _vk_from_char(ch):
    if len(ch) != 1:
        raise ValueError("按键需为单个字符")
    c = ch.upper()
    if "A" <= c <= "Z":
        return ord(c)
    if "0" <= c <= "9":
        return ord(c)
    special = {
        "ESC": 0x1B, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A,
        "F12": 0x7B, "SPACE": 0x20, "TAB": 0x09, "BACK": 0x08,
        "ENTER": 0x0D, "DELETE": 0x2E, "INSERT": 0x2D, "HOME": 0x24,
        "END": 0x23, "LEFT": 0x25, "RIGHT": 0x27, "UP": 0x26, "DOWN": 0x28,
    }
    return special.get(c)


def _mod_flags(mods):
    flags = 0
    for m in mods:
        mm = m.upper()
        if mm not in _MOD_MAP:
            raise ValueError(f"不支持的修饰键: {m}")
        flags |= _MOD_MAP[mm]
    return flags


class GlobalHotkey(QAbstractNativeEventFilter):
    """注册一个全局热键，通过 Qt 原生事件在主线程触发。"""

    def __init__(self, mods, key, callback, id_=0x5145):
        super().__init__()
        self.id = id_
        self._cb = callback
        vk = _vk_from_char(key)
        if vk is None:
            raise ValueError(f"无法解析按键: {key}")
        self._vk = vk
        self._flags = _mod_flags(mods)
        self._user32 = ctypes.windll.user32
        self._user32.RegisterHotKey.argtypes = [
            wt.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        self._user32.RegisterHotKey.restype = ctypes.c_bool

    def register(self):
        """注册热键；失败抛 RuntimeError。"""
        ok = self._user32.RegisterHotKey(None, self.id, self._flags, self._vk)
        if not ok:
            err = ctypes.get_last_error()
            raise RuntimeError(
                f"RegisterHotKey 失败，错误码 {err}（热键可能已被占用）")

    def unregister(self):
        self._user32.UnregisterHotKey(None, self.id)

    def nativeEventFilter(self, event_type, message):
        if event_type == "windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wt.MSG)).contents
            if msg.message == WM_HOTKEY and msg.wParam == self.id:
                try:
                    self._cb()
                except Exception:  # noqa: BLE001
                    pass
                return True, 0
        return False, 0