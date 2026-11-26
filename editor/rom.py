from dataclasses import dataclass
from hashlib import sha256
from math import isqrt
from pathlib import Path

from .charset import Charset
from .international import CHINESE_TABLES, KEY_ITEMS, discover, read_evolution


ROM_HASH = "f4092c50b04a0c471c8e1cda4af1551ac451c754be8ae03f86430c9c0dc0e073"

ITEM_DISABLED = {
    0x07: "废弃的冲浪板会绕过野外通行限制。",
    0x08: "狩猎区球数由独立计数器管理，使用背包中的狩猎球会绕过该流程。",
    0x09: "图鉴由独立剧情旗标解锁，旧道具入口可能在图鉴未初始化时打开列表。",
    **{i: "徽章由剧情位管理。此 ID 是占位符，其中部分还用于狩猎区指令。" for i in range(0x15, 0x1D)},
    0x2C: "ROM 的未使用占位道具。",
    0x32: "ROM 的未使用占位道具。可用的 PP 提升剂是 4F。",
}
ITEM_UNUSUAL = {0x3B: "正常游戏的代币存入代币盒，背包里的代币条目没有使用效果。"}
QUEST_ITEMS = {
    0x05: "城镇地图的领取由劲敌家剧情控制。",
    0x06: "自行车的领取由兑换剧情控制。",
    0x1F: "秘密琥珀由博物馆领取事件控制。",
    0x29: "化石选择与后续复原由独立剧情控制。",
    0x2A: "化石选择与后续复原由独立剧情控制。",
    0x2B: "秘密钥匙用于红莲道馆通行。",
    0x2D: "兑换券由俱乐部剧情发放，兑换由自行车店脚本处理。",
    0x30: "钥匙卡开门时由游戏处理相应门的剧情位。",
    0x3F: "船票供港口检查，船的状态由剧情记录。",
    0x40: "金假牙交给园长时触发秘传学习器奖励。",
    0x45: "代币盒与代币余额各有独立字段。",
    0x46: "包裹用于大木博士的图鉴剧情。",
    0x48: "检视镜供宝可梦塔的幽灵事件检查。",
    0x49: "宝可梦之笛的领取与卡比兽的进度各有独立记录。",
    0x4A: "电梯钥匙用于火箭队基地的电梯。",
}
ITEM_UNIQUE = {0x01, 0x4B, 0x4C, 0x4D, 0x4E, *QUEST_ITEMS, *range(0xC4, 0xC9)}
BLOCK_FINITE_ITEMS = {0x06, 0x2B, 0x2D, 0x30, 0x3F, 0x40, 0x48, 0x49, 0x4A, *range(0xC4, 0xC9)}
EXTERNAL_MOVE_CANDIDATES = {0x54: {0x13, 0x39}, 0x55: {0x13, 0x39}, 0x4C: set(range(1, 165))}
# Levels from the starter, gift, fossil revival and fixed battle scripts.
SCRIPTED_LEVELS = {
    0x99: 5, 0xB0: 5, 0xB1: 5, 0x13: 15, 0x66: 25, 0x2B: 30, 0x2C: 30,
    0x62: 30, 0x5A: 30, 0xAB: 30, 0x84: 30, 0x4A: 50, 0x4B: 50, 0x49: 50, 0x83: 70,
}


def word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def rom_address(bank: int, pointer: int) -> int:
    if not 0 <= pointer < 0x8000:
        raise ValueError(f"无效的 ROM 地址 {bank:02X}:{pointer:04X}")
    return pointer if pointer < 0x4000 else (bank - 1) * 0x4000 + pointer


def save_address(wram: int) -> int:
    return 0x25A3 + wram - 0xD2F7


@dataclass(frozen=True)
class Species:
    id: int
    dex: int
    name: str
    raw_name: bytes
    base: tuple[int, ...]
    types: bytes
    catch_rate: int
    growth: int
    starter_moves: tuple[int, ...]
    level_moves: tuple[tuple[int, int], ...]
    machines: frozenset[int]
    evolve: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    key: bool
    disabled: str


class Catalog:
    def __init__(self, rom: bytes):
        self.sha256 = sha256(rom).hexdigest()
        self.verified = self.sha256 == ROM_HASH
        if self.verified:
            self.tables = CHINESE_TABLES
            self.charset = Charset(rom)
            self.version = "简体中文红版 · 已验证"
        else:
            self.tables, self.charset, self.version = discover(rom)
        self.rom = rom
        self.moves = {0: "— 空招式 —", **self.read_names(self.tables.move_names, 165)}
        self.base_pp = {0: 0, **{i: rom[self.tables.moves + (i - 1) * 6 + 5] for i in range(1, 166)}}
        self.species = self.read_species()
        self.by_dex = sorted(self.species.values(), key=lambda s: s.dex)
        self.parents = {target: (mon.id, kind, param) for mon in self.by_dex
                        for kind, param, target in mon.evolve}
        self.minimum_levels = self.read_minimum_levels() if self.verified else {}
        self.items = self.read_items()

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        with path.open("rb") as source:
            return cls(source.read(0x200001))

    def read_names(self, address: int, count: int) -> dict[int, str]:
        result = {}
        for i in range(1, count + 1):
            end = self.rom.find(b"\x50", address, address + 64)
            if end < 0:
                raise ValueError("ROM 名称表缺少结束符。")
            result[i] = self.charset.decode(self.rom[address:end], rom_text=True)
            address = end + 1
        return result

    def read_species(self) -> dict[int, Species]:
        data = self.rom
        tables = self.tables
        result = {}
        species_ids = {i + 1 for i, n in enumerate(data[tables.dex:tables.dex + 190]) if n}
        for id_, dex in enumerate(data[tables.dex:tables.dex + 190], 1):
            if dex == 0:
                continue
            base_offset = tables.mew if dex == 151 else tables.bases + (dex - 1) * 28
            base = data[base_offset:base_offset + 28]
            name_offset = tables.species_names + (id_ - 1) * 10
            name = data[name_offset:name_offset + 10]
            pointer = word(data, tables.evolutions + (id_ - 1) * 2)
            evolutions, learned = read_evolution(data, pointer, tables.evolutions // 0x4000, species_ids)
            machines = frozenset(data[tables.machines + j] for j in range(55) if base[20 + j // 8] & (1 << (j % 8)))
            result[id_] = Species(
                id_, dex, self.charset.decode(name), name + b"\x50", tuple(base[1:6]),
                base[6:8], base[8], base[19], tuple(base[15:19]), tuple(learned),
                machines, tuple(evolutions),
            )
        if sorted(s.dex for s in result.values()) != list(range(1, 152)):
            raise ValueError("ROM 的图鉴编号表与此版本不符。")
        return result

    def read_minimum_levels(self) -> dict[int, int]:
        rom = self.rom
        levels = SCRIPTED_LEVELS.copy()

        def record(species, level):
            levels[species] = min(level, levels.get(species, 101))

        def read_pairs(start, count):
            for offset in range(start, start + count * 2, 2):
                record(rom[offset + 1], rom[offset])

        # Each grass/water table starts with an encounter rate. A nonzero
        # rate is followed by ten level/species pairs.
        pointers = {word(rom, at) for at in range(0xCEEB, 0xD0C9, 2)}
        for pointer in pointers:
            entry = rom_address(3, pointer)
            for _ in range(2):
                size = 10 if rom[entry] else 0
                read_pairs(entry + 1, size)
                entry += 1 + size * 2
        record(rom[0xE28B], rom[0xE28C])  # Old Rod
        read_pairs(0xE2B7, 2)  # Good Rod
        entry = 0xE959  # Super Rod map and group pointers
        while rom[entry] != 255:
            group = rom_address(3, word(rom, entry + 1))
            read_pairs(group + 1, rom[group])
            entry += 3
        for offset in range(0x52964, 0x52970, 2):
            record(rom[offset], rom[offset + 1])

        # Field and NPC trades keep the offered mon's level. Both ROM
        # language tables have the same species pairs, and slot 2 is unused.
        trades = [(rom[at], rom[at + 1])
                  for at in range(0x71B39, 0x71BC5, 14) if at != 0x71B39 + 2 * 14]
        while True:
            previous = levels.copy()
            for source, target in trades:
                if source in levels:
                    record(target, levels[source])
            for target, (source, method, parameter) in self.parents.items():
                if source in levels:
                    level = max(levels[source] + 1, parameter) if method == 1 else levels[source]
                    if level <= 100:
                        record(target, level)
            if previous == levels:
                return levels

    def read_items(self) -> dict[int, Item]:
        names = self.read_names(self.tables.item_names, 83)
        result = {}
        for i, n in names.items():
            key = i in KEY_ITEMS
            result[i] = Item(i, n, key, ITEM_DISABLED.get(i, ""))
        for i in range(0xC4, 0xFB):
            hm = i < 0xC9
            num = i - (0xC4 if hm else 0xC9)
            move = self.rom[self.tables.machines + (50 if hm else 0) + num]
            result[i] = Item(i, f"{'HM' if hm else 'TM'}{num + 1:02d} {self.moves[move]}", hm, "")
        return result

    def experience(self, species: int, level: int) -> int:
        growth = self.species[species].growth
        at = self.tables.growth + growth * 4
        cubic, square, linear, constant = self.rom[at:at + 4]
        squared = -(square & 0x7F) if square & 0x80 else square
        return max(0, (cubic >> 4) * level**3 // (cubic & 15) + squared * level**2 + linear * level - constant)

    def level(self, species: int, exp: int) -> int:
        low, high = 1, 101
        while high - low > 1:
            middle = (high + low) // 2
            if exp < self.experience(species, middle):
                high = middle
            else:
                low = middle
        return low

    def stats(self, species: int, level: int, iv: tuple[int, ...], effort: tuple[int, ...]) -> tuple[int, ...]:
        bases = self.species[species].base
        roots = [min(255, 0 if e == 0 else 1 + isqrt(e - 1)) for e in effort]
        return tuple(min(999, ((base + dv) * 2 + root // 4) * level // 100 + (level + 10 if i == 0 else 5))
                     for i, (base, dv, root) in enumerate(zip(bases, (hp_iv(iv), *iv), roots, strict=True)))

    def max_pp(self, move: int, ups: int) -> int:
        base = self.base_pp[move]
        return base + min(7, base // 5) * ups

    def suggested_moves(self, species: int, level: int) -> tuple[int, ...]:
        mon = self.species[species]
        options = [m for m in mon.starter_moves if m]
        for at, learned in mon.level_moves:
            if at <= level and learned not in options:
                options.append(learned)
        moves = options[-4:]
        return tuple(moves + [0] * (4 - len(moves)))

    def move_rule(self, species: int, level: int, move: int) -> tuple[str, str]:
        if move == 0:
            return "normal", "此槽为空。"
        if move == 0xA5 or move not in self.moves:
            return "disabled", "挣扎由战斗在 PP 耗尽时自动调用，无法作为可选的固定招式。" if move == 0xA5 else "招式 ID 不在 ROM 的有效表内。"
        current = species
        minimum = None
        external = False
        while True:
            mon = self.species[current]
            external |= move in EXTERNAL_MOVE_CANDIDATES.get(current, ())
            if move in mon.machines or move in mon.starter_moves:
                return "normal", "当前形态或进化前形态可通过初始招式或学习器取得。"
            for threshold, learned in mon.level_moves:
                if learned == move:
                    minimum = threshold if minimum is None else min(minimum, threshold)
            if current not in self.parents:
                break
            current = self.parents[current][0]
        if minimum is not None and minimum <= level:
            return "normal", f"当前形态或进化前形态可在 {minimum} 级习得。"
        if external:
            return "unknown", "此外部版本、活动配布或变身遗留组合的来源待验证。"
        if minimum:
            return "unusual", f"升级学习至少需要 {minimum} 级。"
        return "unusual", "本 ROM 中当前及进化前形态均无初始、升级或学习器途径。"

    def species_rule(self, species: int, level: int) -> tuple[str, str]:
        if self.species[species].dex == 151:
            return "unusual", "此 ROM 的常规流程无法取得梦幻。"
        minimum = self.minimum_levels.get(species)
        if minimum is None:
            return "unknown", "本 ROM 未找到直接取得途径，外部版本的交换来源待验证。"
        if level < minimum:
            return "unusual", f"本 ROM 已核实的捕获、奖励、交换和进化途径最低为 {minimum} 级。"
        return "normal", ""


def hp_iv(iv: tuple[int, ...]) -> int:
    return sum((value & 1) << (3 - i) for i, value in enumerate(iv))
