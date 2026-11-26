"""Locate the common Generation I tables in international Red, Blue and Yellow."""
from dataclasses import dataclass

from .charset import JapaneseCharset, SingleByteCharset


@dataclass(frozen=True)
class RomTables:
    species_names: int
    move_names: int
    item_names: int
    moves: int
    bases: int
    mew: int
    dex: int
    machines: int
    growth: int
    evolutions: int
    name_stride: int = 10


CHINESE_TABLES = RomTables(
    0x1C98A, 0xB0000, 0x470E, 0x38000, 0x383DE, 0x4262,
    0x40FC2, 0x1391B, 0x59015, 0x3B01E,
)
KEY_ITEMS = frozenset({
    5, 6, 7, 8, 9, *range(0x15, 0x1D), 0x1F, 0x29, 0x2A, 0x2B, 0x2C,
    0x2D, 0x30, 0x3F, 0x40, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4C, 0x4D, 0x4E,
})
LANGUAGES = (
    ("en", "英文", "RHYDON", "KANGASKHAN", "POUND", "MASTER BALL"),
    ("fr", "法文", "RHINOFEROS", "KANGOUREX", "ECRAS'FACE", "MASTER BALL"),
    ("de", "德文", "RIZEROS", "KANGAMA", "PFUND", "MEISTERBALL"),
    ("es", "西班牙文", "RHYDON", "KANGASKHAN", "DESTRUCTOR", "MASTER BALL"),
    ("it", "意大利文", "RHYDON", "KANGASKHAN", "LIBBRA", "MASTER BALL"),
)


def unique(rom: bytes, signature: bytes, label: str) -> int:
    start = rom.find(signature)
    if start < 0 or rom.find(signature, start + 1) >= 0:
        raise ValueError(f"无法唯一定位此 ROM 的{label}，请反馈 ROM 的 SHA-256。")
    return start


def read_evolution(rom: bytes, pointer: int, bank: int, species_ids: set[int]):
    if not 0x4000 <= pointer < 0x8000:
        raise ValueError("进化表指针越界。")
    end = (bank + 1) * 0x4000
    position = bank * 0x4000 + pointer - 0x4000
    evolution = []
    for _ in range(5):
        if position + 4 > end:
            raise ValueError("进化表越界。")
        method = rom[position]
        if method == 0:
            position += 1
            break
        if method not in (1, 2, 3):
            raise ValueError("进化方式无效。")
        size = 4 if method == 2 else 3
        parameter, target = rom[position + 1], rom[position + size - 1]
        if target not in species_ids or not 1 <= parameter <= 100:
            raise ValueError("进化参数无效。")
        evolution.append((method, parameter, target))
        position += size
    else:
        raise ValueError("进化表缺少结束符。")
    learned = []
    for _ in range(33):
        if position + 2 > end:
            raise ValueError("升级招式表越界。")
        level = rom[position]
        if not level:
            return tuple(evolution), tuple(learned)
        move = rom[position + 1]
        if not 1 <= level <= 100 or not 1 <= move <= 164:
            raise ValueError("升级招式数据无效。")
        learned.append((level, move))
        position += 2
    raise ValueError("升级招式表缺少结束符。")


def find_evolutions(rom: bytes, bases: int, dex: bytes) -> int:
    bank = bases // 0x4000
    species_ids = {i + 1 for i, number in enumerate(dex) if number}
    candidates = []
    for start in range(bases + 150 * 28, (bank + 1) * 0x4000 - 380):
        try:
            for species in sorted(species_ids):
                at = start + (species - 1) * 2
                pointer = int.from_bytes(rom[at:at + 2], "little")
                read_evolution(rom, pointer, bank, species_ids)
        except ValueError:
            continue
        candidates.append(start)
    if len(candidates) != 1:
        raise ValueError("无法唯一定位此 ROM 的进化与升级招式表。")
    return candidates[0]


def discover(rom: bytes):
    if len(rom) < 0x80000:
        raise ValueError("未定位原版数据表，改用参考资料。")
    title = rom[0x134:0x143].split(b"\0", 1)[0].decode("ascii", errors="replace")
    if not title.startswith(("POKEMON", "POCKET MONS")):
        raise ValueError("ROM 文件头不是国际版红、蓝、黄。")
    japanese = rom[0x14A] == 0
    if not any(name in title for name in ("RED", "GREEN", "BLUE", "YELLOW", "ROUGE", "BLEU", "ROT", "BLAU", "ROSS", "ROJ", "AZUL", "GELB", "JAUNE", "GIAL", "AMAR")):
        raise ValueError(f"无法识别 ROM 标题「{title}」。")
    if ((-sum(rom[0x134:0x14D]) - 25) & 255) != rom[0x14D]:
        raise ValueError("ROM 文件头校验错误。")
    selected = []
    languages = (("ja", "日文", "サイドン", "ガルーラ", "はたく", "マスターボール"),) if japanese else LANGUAGES
    stride = 5 if japanese else 10
    for language, label, first, second, move, item in languages:
        codec = JapaneseCharset() if japanese else SingleByteCharset(language)
        names_signature = codec.nickname(first)[:stride] + codec.nickname(second)[:stride]
        names = rom.find(names_signature)
        moves = rom.find(codec.nickname(move)[:len(move)] + b"\x50")
        if names >= 0 and moves >= 0:
            selected.append((codec, label, names, moves, item))
    if len(selected) != 1:
        raise ValueError("无法识别此 ROM 的国际版语言数据表。")
    codec, language, names, move_names, item = selected[0]
    item_signature = b"".join(codec.encoding[char] for char in item) + b"\x50"
    item_names = unique(rom, item_signature, "道具名称表")
    bases = unique(rom, bytes((1, 45, 49, 49, 45, 65, 22, 3, 45, 64)), "种族能力表")
    for number in range(1, 151):
        if rom[bases + (number - 1) * 28] != number:
            raise ValueError("种族能力表的图鉴编号顺序异常。")
    mew = unique(rom, bytes((151, 100, 100, 100, 100, 100, 24, 24, 45)), "梦幻能力表")
    dex = unique(rom, bytes((112, 115, 32, 35, 21, 100, 34, 80, 2, 103, 108, 102)), "内部种类索引")
    dex_data = rom[dex:dex + 190]
    if sorted(n for n in dex_data if n) != list(range(1, 152)):
        raise ValueError("内部种类索引不符合初代的 151 种精灵。")
    moves = unique(rom, bytes((1, 0, 40, 0, 255, 35, 2, 0, 50, 0, 255, 25)), "招式能力表")
    for number in range(1, 166):
        offset = moves + (number - 1) * 6
        if rom[offset] != number or not 1 <= rom[offset + 5] <= 40:
            raise ValueError("招式能力或 PP 表异常。")
    machines = unique(rom, bytes((5, 13, 14, 18, 25, 92, 32, 34, 36, 38, 61, 55, 58, 59)), "学习器表")
    growth = unique(rom, bytes.fromhex("11000000340a001e34140046658f648c4500000054000000"), "经验成长表")
    evolutions = find_evolutions(rom, bases, dex_data)
    revision = rom[0x14C]
    tables = RomTables(names, move_names, item_names, moves, bases, mew, dex, machines, growth, evolutions, stride)
    return tables, codec, f"{title} · {language} · Rev {revision} · 未认证"
