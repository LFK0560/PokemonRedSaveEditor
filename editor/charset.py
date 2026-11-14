from functools import cached_property


END = 0x50
NAME_BYTES = 11
FONT_POINTERS = 0x104450
CHINESE_LEADS = (*range(4, 0x14), *range(0x18, 0x20), *range(0x28, 0x2F))

SINGLE = {
    **{i + 0x80: c for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
    **{i + 0xA0: c for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{i + 0xF6: c for i, c in enumerate("0123456789")},
    0x7F: " ", 0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";",
    0x9E: "[", 0x9F: "]", 0xBA: "é", 0xBB: "'d", 0xBC: "'l",
    0xBD: "'s", 0xBE: "'t", 0xBF: "'v", 0xE0: "'", 0xE3: "-",
    0xE4: "'r", 0xE5: "'m", 0xE6: "?", 0xE7: "!", 0xE8: ".",
    0xEF: "♂", 0xF0: "¥", 0xF1: "×", 0xF2: ".", 0xF3: "/",
    0xF4: ",", 0xF5: "♀",
}

# The patch interprets these as dictionary tokens in ROM strings.
TEXT_TOKEN = {0x4A: "宝可梦", 0x54: "宝可梦", 0x5B: "PC", 0x5C: "TM", 0x5E: "火箭队"}
SYMBOLS = {
    0x0101: "　", 0x0102: "、", 0x0103: "。", 0x0105: "ˉ",
    0x0106: "ˇ", 0x0107: "¨", 0x0108: "〃", 0x0109: "々", 0x010A: "—",
    0x010B: "～", 0x010C: "‖", 0x010D: "…", 0x010E: "‘", 0x010F: "’",
    0x0110: "“", 0x0111: "”", 0x0112: "〔", 0x0113: "〕", 0x0117: "〈",
    0x0118: "〉", 0x0119: "《", 0x011A: "》", 0x011B: "「", 0x011C: "」",
    0x011D: "『", 0x011E: "』", 0x0121: "【", 0x0123: "】", 0x0124: "±",
    0x0125: "×", 0x0126: "÷", 0x0146: "♂", 0x0147: "♀", 0x0160: "℃",
    0x0168: "☆", 0x0169: "★", 0x016A: "○", 0x016B: "●",
    0x016D: "◇", 0x016E: "◆", 0x0171: "△", 0x0172: "▲",
    0x0174: "→", 0x0175: "←", 0x0176: "↑", 0x0177: "↓",
    0x2EB7: "HP", 0x2EB8: "哆", 0x2EB9: "kg", 0x2EBA: "PP",
}


def gb2312_characters(first: int, stop: int) -> list[str]:
    characters = []
    for lead in range(first, stop):
        for trail in range(0xA1, 0xFF):
            character = bytes((lead, trail)).decode("gb2312", errors="ignore")
            if character:
                characters.append(character)
    return characters


class Charset:
    def __init__(self, rom: bytes):
        self.rom = rom

    def glyph(self, code: int) -> bytes:
        lead, trail = divmod(code, 256)
        pointer = FONT_POINTERS + 3 * (lead * 2 + (trail >> 7))
        address = int.from_bytes(self.rom[pointer:pointer + 2], "little")
        bank = self.rom[pointer + 2]
        offset = (bank - 1) * 0x4000 + address + (trail & 127) * 18
        return self.rom[offset:offset + 18]

    @staticmethod
    def glyph_rows(glyph: bytes) -> tuple[int, ...]:
        rows = []
        for row in range(12):
            shift = 4 if row % 2 == 0 else 0
            strips = [(glyph[offset + row // 2] >> shift) & 15 for offset in (0, 6, 12)]
            rows.append(strips[0] << 8 | strips[1] << 4 | strips[2])
        return tuple(rows)

    @cached_property
    def chinese(self) -> dict[int, str]:
        # The localization packs GB2312 ideographs in order across three banks
        # per block. Its unused cells contain the cell's own hex code or zeros.
        digits = {}
        for digit in range(16):
            lead = digit if 4 <= digit <= 7 else digit + 0x10
            rows = self.glyph_rows(self.glyph(lead << 8))
            digits[digit] = tuple((v >> 1) & 31 for v in rows[:5])

        def has_glyph(code: int) -> bool:
            rows = self.glyph_rows(self.glyph(code))
            if not any(rows):
                return False
            if rows[5] or rows[11]:
                return True
            for x, y, shift in ((7, 0, 12), (1, 0, 8), (7, 6, 4), (1, 6, 0)):
                part = tuple((v >> x) & 31 for v in rows[y:y + 5])
                if part != digits[(code >> shift) & 15]:
                    return True
            return False

        codes = [lead * 256 + trail for lead in CHINESE_LEADS for trail in range(256)
                 if 0x04C3 <= lead * 256 + trail <= 0x2EB6 and has_glyph(lead * 256 + trail)]
        characters = gb2312_characters(0xB0, 0xF8)
        if len(codes) != len(characters):
            raise ValueError("ROM 字库的汉字数量与此版本不符。")
        return dict(zip(codes, characters, strict=True)) | SYMBOLS

    @cached_property
    def encoding(self) -> dict[str, bytes]:
        result = {c: i.to_bytes(2, "big") for i, c in self.chinese.items() if len(c) == 1}
        result.update({c: bytes((i,)) for i, c in SINGLE.items() if len(c) == 1})
        return result

    def decode(self, data: bytes, *, rom_text: bool = False) -> str:
        index = 0
        result = []
        while index < len(data):
            value = data[index]
            index += 1
            if value == END:
                break
            if value < 0x30 and index < len(data):
                code = value * 256 + data[index]
                index += 1
                result.append(self.chinese.get(code, f"〈{code:04X}〉"))
            elif rom_text and value in TEXT_TOKEN:
                result.append(TEXT_TOKEN[value])
            else:
                result.append(SINGLE.get(value, f"〈{value:02X}〉"))
        return "".join(result)

    def string_end(self, data: bytes) -> int | None:
        index = 0
        while index < len(data):
            value = data[index]
            if value == END:
                return index
            if value < 0x30:
                if index + 1 == len(data) or data[index + 1] == END:
                    return None
                index += 1
            index += 1
        return None

    def valid_stored_name(self, data: bytes) -> bool:
        end = self.string_end(data)
        return end is not None and end > 0

    def nickname(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("请输入昵称。")
        for c in text:
            if c not in self.encoding:
                raise ValueError(f"ROM 字库中没有可用于昵称的字符「{c}」。")
        data = b"".join(self.encoding[c] for c in text)
        if len(data) > NAME_BYTES - 1:
            raise ValueError(f"昵称用了 {len(data)} 字节，最多可用 10 字节（一般每个汉字 2 字节）。")
        return data.ljust(NAME_BYTES, bytes((END,)))
