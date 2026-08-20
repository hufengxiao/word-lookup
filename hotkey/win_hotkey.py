"""
全局热键：独立守护线程 + RegisterHotKey + GetMessageW。

原理（最底层、可控）：
  1. 起一个独立守护线程，在线程内调用 user32.RegisterHotKey(NULL, id, mods, vk)。
     hWnd 传 NULL 时，WM_HOTKEY 消息投递到「注册线程」（即本线程）的消息队列。
  2. 线程内用 GetMessageW 阻塞等待消息——WM_HOTKEY 到来即回调。
  3. 回调通过 Qt 信号（QObject.emit）跨线程 AutoConnection 投递到主线程执行 UI，
     这是 Qt 官方的跨线程 UI 调用方式，可靠。

为什么不用 QAbstractNativeEventFilter：
  PySide6 各版本对 eventType(QByteArray) 与 Python str/bytes 的比较、以及 message
  指针的 int(message) 转换行为不一致，导致过滤器可能永不触发。独立线程 + 原生
  消息循环对类型无歧义，每一环都可加日志直观测到。
"""
import ctypes
import ctypes.wintypes as wt
import threading

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


class GlobalHotkey(threading.Thread):
    """注册一个全局热键并在独立线程监听。用 .start() 启动。"""

    def __init__(self, mods, key, callback, id_=0x5145, log=None):
        super().__init__(daemon=True)
        self.mods = mods
        self.key = key
        self.id = id_
        self._cb = callback
        self._log = log or (lambda *a: None)
        self._vk = _vk_from_char(key)
        if self._vk is None:
            raise ValueError(f"无法解析按键: {key}")
        self._flags = _mod_flags(mods)
        self._running = False
        self._registered = threading.Event()
        self._register_ok = False
        self._register_err = None
        self._user32 = ctypes.windll.user32
        self._user32.RegisterHotKey.argtypes = [
            wt.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        self._user32.RegisterHotKey.restype = ctypes.c_bool

    def run(self):
        """线程体：注册热键 + 消息循环。"""
        try:
            ok = self._user32.RegisterHotKey(
                None, self.id, self._flags, self._vk)
            if not ok:
                err = ctypes.get_last_error()
                raise RuntimeError(
                    f"RegisterHotKey 失败, 错误码 {err} (热键可能被占用)")
            self._register_ok = True
            self._log("[hotkey-thread] RegisterHotKey OK")
        except Exception as e:  # noqa: BLE001
            self._register_err = str(e)
            self._log(f"[hotkey-thread] RegisterHotKey FAILED: {e}")
            self._registered.set()
            return
        self._registered.set()

        msg = wt.MSG()
        self._log("[hotkey-thread] message loop start")
        while self._running:
            r = self._user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if r == 0:
                break  # WM_QUIT
            if r == -1:
                self._log(f"[hotkey-thread] GetMessageW error {ctypes.get_last_error()}")
                break
            if msg.message == WM_HOTKEY and msg.wParam == self.id:
                self._log("[hotkey-thread] WM_HOTKEY -> invoke callback")
                try:
                    self._cb()
                except Exception as e:  # noqa: BLE001
                    self._log(f"[hotkey-thread] callback error: {e}")
            else:
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
        self._log("[hotkey-thread] message loop exit")

    def start(self, wait=True):
        """启动线程。wait=True 时阻塞直到热键注册结果确定。"""
        if self.is_alive():
            return
        self._running = True
        self._registered.clear()
        super().start()
        if wait:
            self._registered.wait(timeout=5.0)
            if not self._register_ok:
                raise RuntimeError(self._register_err or "热键注册失败/超时")

    def stop(self):
        """停止线程。"""
        self._running = False
        if self.is_alive():
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self.ident, 0x0012, 0, 0)  # WM_QUIT
            except Exception:  # noqa: BLE001
                pass
            self.join(timeout=1.0)
        try:
            self._user32.UnregisterHotKey(None, self.id)
        except Exception:  # noqa: BLE001
            pass