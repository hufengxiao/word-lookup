"""
MDX 词典解析器。

MDict (MDX) 格式解析。算法参考开源 readmdict (GPL-3.0)，做了重构：
  - 解耦 LZO 解压到 `lzo` 模块，跨平台可用
  - 提供按需读取单条词条正文的高效接口
  - 惰性加载，尽量轻量

本解析器用于轻量查词工具，无需把整个词典解压到内存。
"""
import re
import struct
import zlib
from io import BytesIO

from . import lzo
from .ripemd128 import ripemd128

# MDX 头部标记字段的常量
_UNESCAPE_MAP = [
    (b"&lt;", b"<"),
    (b"&gt;", b">"),
    (b"&quot;", b'"'),
    (b"&amp;", b"&"),
]


def _unescape_entities(text: bytes) -> bytes:
    for a, b in _UNESCAPE_MAP:
        text = text.replace(a, b)
    return text


def _fast_decrypt(data: bytes, key: bytes) -> bytes:
    b = bytearray(data)
    key = bytearray(key)
    previous = 0x36
    for i in range(len(b)):
        t = (b[i] >> 4 | b[i] << 4) & 0xFF
        t = t ^ previous ^ (i & 0xFF) ^ key[i % len(key)]
        previous = b[i]
        b[i] = t
    return bytes(b)


def _mdx_decrypt(comp_block: bytes) -> bytes:
    key = ripemd128(comp_block[4:8] + struct.pack("<L", 0x3695))
    return comp_block[0:8] + _fast_decrypt(comp_block[8:], key)


class MDX:
    """
    MDX 词典文件读取器。

    >>> mdx = MDX('oxford.mdx')
    >>> len(mdx)
    156381
    >>> keys = mdx.keys()
    >>> html = mdx.lookup(b'apple')
    """

    def __init__(self, fname: str, encoding: str = ""):
        self._fname = fname
        self._encoding = encoding.upper()
        self._stylesheet = {}
        self._key_block_offset = 0
        self._record_block_offset = 0
        self._num_entries = 0
        self._version = 0.0
        self._encrypt = 0
        self._number_width = 4
        self._number_format = ">I"
        self.header = {}
        self._key_list = []  # [(key_id, key_text_bytes), ...]

        self._read_header()
        self._read_keys()

        # 供按需读取正文用
        self._entries = None  # 惰性构建 {key_text: offset} 的映射（用自定义二分）
        self._sorted_keys = None

    # ------------------------------------------------------------------
    # 基础读取
    # ------------------------------------------------------------------
    def _read_number(self, f) -> int:
        return struct.unpack(self._number_format, f.read(self._number_width))[0]

    def _parse_header(self, header: bytes) -> dict:
        taglist = re.findall(rb'(\w+)="(.*?)"', header, re.DOTALL)
        tagdict = {}
        for key, value in taglist:
            tagdict[key] = _unescape_entities(value)
        return tagdict

    def _read_header(self):
        f = open(self._fname, "rb")
        header_bytes_size = struct.unpack(">I", f.read(4))[0]
        header_bytes = f.read(header_bytes_size)
        adler32 = struct.unpack("<I", f.read(4))[0]
        assert adler32 == (zlib.adler32(header_bytes) & 0xFFFFFFFF)
        self._key_block_offset = f.tell()
        f.close()

        header_text = header_bytes[:-2].decode("utf-16").encode("utf-8")
        header_tag = self._parse_header(header_text)

        if not self._encoding:
            encoding = header_tag[b"Encoding"]
            try:
                encoding = encoding.decode("utf-8")
            except Exception:
                pass
            if encoding in ("GBK", "GB2312"):
                encoding = "GB18030"
            self._encoding = encoding

        # 加密标志
        if b"Encrypted" not in header_tag or header_tag[b"Encrypted"] == b"No":
            self._encrypt = 0
        elif header_tag[b"Encrypted"] == b"Yes":
            self._encrypt = 1
        else:
            try:
                self._encrypt = int(header_tag[b"Encrypted"])
            except (ValueError, TypeError):
                self._encrypt = 0

        # 样式表
        if header_tag.get(b"StyleSheet"):
            lines = header_tag[b"StyleSheet"].splitlines()
            for i in range(0, len(lines), 3):
                self._stylesheet[lines[i]] = (lines[i + 1], lines[i + 2])

        # 版本
        ver = header_tag.get(b"GeneratedByEngineVersion", b"2.0")
        self._version = float(ver)
        if self._version < 2.0:
            self._number_width = 4
            self._number_format = ">I"
        else:
            self._number_width = 8
            self._number_format = ">Q"

        self.header = {
            k.decode("utf-8", "replace"): v.decode("utf-8", "replace")
            for k, v in header_tag.items()
        }

    # ------------------------------------------------------------------
    # Key（词条索引）解析
    # ------------------------------------------------------------------
    def _decode_key_block_info(self, key_block_info_compressed: bytes):
        if self._version >= 2:
            assert key_block_info_compressed[:4] == b"\x02\x00\x00\x00"
            if self._encrypt & 0x02:
                key_block_info_compressed = _mdx_decrypt(key_block_info_compressed)
            key_block_info = zlib.decompress(key_block_info_compressed[8:])
            adler32 = struct.unpack(">I", key_block_info_compressed[4:8])[0]
            assert adler32 == zlib.adler32(key_block_info) & 0xFFFFFFFF
        else:
            key_block_info = key_block_info_compressed

        key_block_info_list = []
        i = 0
        if self._version >= 2:
            byte_format, byte_width, text_term = ">H", 2, 1
        else:
            byte_format, byte_width, text_term = ">B", 1, 0

        while i < len(key_block_info):
            i += self._number_width  # 当前 key block 内的词条数
            text_head_size = struct.unpack(byte_format, key_block_info[i:i + byte_width])[0]
            i += byte_width
            if self._encoding != "UTF-16":
                i += text_head_size + text_term
            else:
                i += (text_head_size + text_term) * 2
            text_tail_size = struct.unpack(byte_format, key_block_info[i:i + byte_width])[0]
            i += byte_width
            if self._encoding != "UTF-16":
                i += text_tail_size + text_term
            else:
                i += (text_tail_size + text_term) * 2
            compressed_size = struct.unpack(self._number_format, key_block_info[i:i + self._number_width])[0]
            i += self._number_width
            decompressed_size = struct.unpack(self._number_format, key_block_info[i:i + self._number_width])[0]
            i += self._number_width
            key_block_info_list.append((compressed_size, decompressed_size))

        return key_block_info_list

    def _decode_key_block(self, key_block_compressed: bytes, key_block_info_list):
        key_list = []
        i = 0
        for compressed_size, decompressed_size in key_block_info_list:
            start, end = i, i + compressed_size
            block = key_block_compressed[start:end]
            if block[:4] == b"\x00\x00\x00\x00":
                key_block = block[8:]
            elif block[:4] == b"\x01\x00\x00\x00":
                key_block = lzo.decompress(block, decompressed_size)
            elif block[:4] == b"\x02\x00\x00\x00":
                key_block = zlib.decompress(block[8:])
            else:
                key_block = b""
            key_list.extend(self._split_key_block(key_block))
            i += compressed_size
        return key_list

    def _split_key_block(self, key_block: bytes):
        key_list = []
        idx = 0
        if self._encoding == "UTF-16":
            delimiter, width = b"\x00\x00", 2
        else:
            delimiter, width = b"\x00", 1
        while idx < len(key_block):
            key_id = struct.unpack(self._number_format, key_block[idx:idx + self._number_width])[0]
            i = idx + self._number_width
            end = -1
            while i < len(key_block):
                if key_block[i:i + width] == delimiter:
                    end = i
                    break
                i += width
            if end < 0:
                break
            key_text = key_block[idx + self._number_width:end].decode(
                self._encoding, errors="ignore"
            ).encode("utf-8").strip()
            key_list.append((key_id, key_text))
            idx = end + width
        return key_list

    def _read_keys(self):
        f = open(self._fname, "rb")
        f.seek(self._key_block_offset)

        num_bytes = 8 * 5 if self._version >= 2.0 else 4 * 4
        block = f.read(num_bytes)

        if self._encrypt & 1:
            # 需要用户身份（注册码）解密，本工具不处理带 user-id 加密的词典
            f.close()
            raise RuntimeError("该词典使用了需要用户注册信息的加密，无法解析")

        sf = BytesIO(block)
        _num_key_blocks = self._read_number(sf)
        self._num_entries = self._read_number(sf)
        if self._version >= 2.0:
            self._read_number(sf)  # key_block_info_decomp_size
        key_block_info_size = self._read_number(sf)
        key_block_size = self._read_number(sf)

        if self._version >= 2.0:
            adler32 = struct.unpack(">I", f.read(4))[0]
            assert adler32 == (zlib.adler32(block) & 0xFFFFFFFF)

        key_block_info = f.read(key_block_info_size)
        key_block_info_list = self._decode_key_block_info(key_block_info)

        key_block_compressed = f.read(key_block_size)
        self._key_list = self._decode_key_block(key_block_compressed, key_block_info_list)
        self._record_block_offset = f.tell()
        f.close()

    # ------------------------------------------------------------------
    # 记录(正文)读取
    # ------------------------------------------------------------------
    def _iter_record_blocks(self):
        """按 record block 逐个解压并产出 (key_text_bytes, html_bytes)。"""
        f = open(self._fname, "rb")
        f.seek(self._record_block_offset)

        num_record_blocks = self._read_number(f)
        _num_entries = self._read_number(f)  # 应等于 self._num_entries
        _record_block_info_size = self._read_number(f)
        _record_block_size = self._read_number(f)

        record_block_info_list = []
        for _ in range(num_record_blocks):
            cs = self._read_number(f)
            ds = self._read_number(f)
            record_block_info_list.append((cs, ds))

        offset = 0
        i = 0
        for compressed_size, decompressed_size in record_block_info_list:
            record_block_compressed = f.read(compressed_size)
            record_block = lzo.decompress(record_block_compressed, decompressed_size)

            # 按 offset 切分
            while i < len(self._key_list):
                record_start, key_text = self._key_list[i]
                if record_start - offset >= len(record_block):
                    break
                record_end = (
                    self._key_list[i + 1][0]
                    if i < len(self._key_list) - 1
                    else len(record_block) + offset
                )
                i += 1
                data = record_block[record_start - offset: record_end - offset]
                record = data.decode(self._encoding, errors="ignore").strip("\x00").encode("utf-8")
                yield key_text, record
            offset += len(record_block)

        f.close()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def __len__(self):
        return self._num_entries

    def keys(self):
        """返回词条名迭代器（utf-8 bytes）。"""
        return (key for _key_id, key in self._key_list)

    def key_texts(self):
        """返回所有词条名（str 列表）。"""
        return [k.decode("utf-8", "replace") for _id, k in self._key_list]

    def build_lookup_table(self):
        """构建 key_id -> key_text 索引与 key_text -> key_id 查找表。

        返回值 (text_list, id_by_text)：
          - text_list: 排好序的 key 文本列表（str），下标即 key_id
          - id_by_text: {key_text_lower: key_id}
        排序基于小写形式，支持不区分大小写的快速定位。
        """
        pairs = []
        for key_id, key_text in self._key_list:
            text = key_text.decode("utf-8", "replace")
            pairs.append((key_id, text))
        pairs.sort(key=lambda p: p[1].lower())
        text_list = [t for _id, t in pairs]
        id_by_text = {}
        for key_id, text in self._key_list:
            id_by_text[text.lower()] = key_id
        return text_list, id_by_text

    def lookup(self, key_text):
        """精确查找一个词条的 HTML（返回 HTML 字节串；不存在返回 None）。

        key_text: str 或 bytes，大小写不敏感。
        """
        if isinstance(key_text, str):
            key_text = key_text.encode("utf-8")
        target = key_text.lower()
        for _kid, ktext in self._key_list:
            if ktext.lower() == target:
                # 找到词条，直接进入 record block 迭代，取到即返回
                for kt, html in self._iter_record_blocks():
                    if kt == ktext:
                        return html
                return None
        return None

    def get_all(self):
        """返回 [(key_str, html_bytes)] 完整列表（大词典耗时较长，慎用）。"""
        return [
            (k.decode("utf-8", "replace"), h)
            for k, h in self._iter_record_blocks()
        ]

    def get_by_key_id(self, key_id, html):
        """供一次性导入时用：key_id 与正文对应。"""
        return html