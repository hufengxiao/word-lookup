"""
LZO 解压适配层。

MDX 词典文件的正文 (record block) 及部分索引块使用 LZO 压缩。
不同平台用不同后端解压：

1. 优先使用 `lzo` (python-lzo) —— Windows 上有预编译 wheel，最简单。
2. 没有 python-lzo 时，尝试用 ctypes 调用系统 C 库：
   - Linux:   liblzo2.so.2 的 lzo1x_decompress
   - macOS:   liblzo2.2.dylib
   - Windows: (需随包携带 liblzo2.dll，或用 python-lzo)

Readmdict 对每个压缩块的实际调用是:
    header = b'\\xf0' + struct.pack('>I', decompressed_size)
    data   = lzo.decompress(header + compressed[8:])

其实 python-lzo 的 `decompress` 会自动读取输出长度。而 ctypes 版本的
lzo1x_decompress 需要显式传入输出长度和缓冲区。两者等价。

本模块对外统一暴露 `decompress(data: bytes, decompressed_size: int) -> bytes`。
"""
import struct
import zlib


def _decompress_ctypes(data_without_type_header, decompressed_size):
    """用 ctypes 调 liblzo2 的 lzo1x_decompress 解压。

    参数 data_without_type_header 是去掉前 8 字节 (type+adler) 后的压缩数据。
    """
    import ctypes

    # 缓存库句柄
    _lib = None
    for name in ("liblzo2.so.2", "liblzo2.so.1", "liblzo2.2.dylib", "liblzo2.dll"):
        try:
            _lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if _lib is None:
        raise RuntimeError(
            "未找到 liblzo2 动态库，请安装 liblzo2 或 python-lzo (pip install python-lzo)"
        )

    _lib.lzo1x_decompress.restype = ctypes.c_int
    _lib.lzo1x_decompress.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
    ]

    in_len = len(data_without_type_header)
    out_buf = ctypes.create_string_buffer(max(decompressed_size, 1))
    out_len = ctypes.c_size_t(decompressed_size)
    rc = _lib.lzo1x_decompress(
        data_without_type_header,
        in_len,
        out_buf,
        ctypes.byref(out_len),
        None,
    )
    if rc != 0:  # LZO_E_OK = 0
        raise RuntimeError(f"LZO 解压失败，返回码 {rc}")
    return out_buf.raw[: out_len.value]


def _decompress_pylzo(data_without_type_header, decompressed_size):
    """用 python-lzo 提供的高级接口解压。"""
    import lzo

    # python-lzo 的 decompress 需要完整数据（含 \\xf0 + 大端长度头）。
    header = b"\xf0" + struct.pack(">I", decompressed_size)
    return lzo.decompress(header + data_without_type_header)


class _LzoBackend:
    """惰性选择可用的 LZO 后端。"""

    def __init__(self):
        self._module = None
        self._mode = None

    def _resolve(self):
        if self._mode is not None:
            return self._mode
        # 1. 尝试 python-lzo
        try:
            import lzo  # noqa: F401

            self._mode = "pylzo"
            return self._mode
        except ImportError:
            pass
        # 2. 尝试 ctypes 调系统库
        import ctypes

        # 2a. 先从应用旁/常见目录找显式的 dll（利于 exe 分发时附带）
        app_roots = []
        try:
            import os
            import sys
            if getattr(sys, "frozen", False):
                app_roots.append(os.path.dirname(sys.executable))
            else:
                app_roots.append(os.path.dirname(os.path.abspath(__file__)))
        except Exception:
            pass
        for root in app_roots:
            cand = os.path.join(root, "liblzo2.dll")
            if os.path.exists(cand):
                try:
                    ctypes.CDLL(cand)
                    self._mode = "ctypes"
                    return self._mode
                except OSError:
                    pass

        # 2b. 系统路径 / PATH
        for name in ("liblzo2.so.2", "liblzo2.so.1", "liblzo2.2.dylib", "liblzo2.dll"):
            try:
                ctypes.CDLL(name)
                self._mode = "ctypes"
                return self._mode
            except OSError:
                continue
        raise RuntimeError(
            "找不到可用的 LZO 后端。请安装 liblzo2 或用 `pip install python-lzo`。"
        )

    def decompress(self, data, decompressed_size):
        mode = self._resolve()
        if mode == "ctypes":
            return _decompress_ctypes(data, decompressed_size)
        return _decompress_pylzo(data, decompressed_size)


_backend = _LzoBackend()


def decompress(compressed_block, decompressed_size):
    """解压一个 MDX 压缩块。

    :param compressed_block: 完整压缩块（含前 4 字节类型标记 + 4 字节 adler）
    :param decompressed_size: 期望的解压后大小
    """
    block_type = compressed_block[:4]
    if block_type == b"\x00\x00\x00\x00":
        # 未压缩，直接返回去掉 8 字节头的内容
        return compressed_block[8:]
    if block_type == b"\x01\x00\x00\x00":
        # LZO 压缩
        return _backend.decompress(compressed_block[8:], decompressed_size)
    if block_type == b"\x02\x00\x00\x00":
        # zlib 压缩
        return zlib.decompress(compressed_block[8:])
    raise ValueError(f"未知的压缩类型: {block_type!r}")