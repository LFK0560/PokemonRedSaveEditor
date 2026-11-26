from dataclasses import dataclass, replace

from .charset import NAME_BYTES
from .rom import BLOCK_FINITE_ITEMS, Catalog, ITEM_UNIQUE, ITEM_UNUSUAL, QUEST_ITEMS, save_address
from .profiles import INTERNATIONAL, JAPANESE, detect_profile


SAVE_SIZE = 0x8000
PLAYER = 0x2598
MAIN_SUM = 0x3523
PARTY = 0x2F2C
ACTIVE_BOX = 0x30C0
BOX_SIZE = 0x462
BOX_BANKS = (0x4000, 0x6000)
BOX_COUNT = 12
BOX_NUMBER = save_address(0xD5A0)
BOX_INITIALIZED = 0x80
PLAYER_ID = save_address(0xD359)
CURRENT_MAP = save_address(0xD35E)
EVENT_FLAGS = save_address(0xD747)
BAG = (save_address(0xD31D), 20)
PC_ITEMS = (save_address(0xD53A), 50)

STAT_NAMES = ("HP", "攻击", "防御", "速度", "特殊")
STATUS = {0: "正常", **{n: f"睡眠（{n} 回合）" for n in range(1, 8)},
          8: "中毒", 16: "灼伤", 32: "冰冻", 64: "麻痹"}


class InvalidSave(ValueError):
    pass


def checksum(data: bytes | bytearray, start: int, end: int) -> int:
    return (~sum(data[start:end])) & 255


def box_offset(box: int, profile=INTERNATIONAL) -> int:
    half = profile.boxes_per_bank
    return BOX_BANKS[box // half] + (box % half) * profile.box_size


def bank_checksum(data: bytearray, bank: int, profile=INTERNATIONAL) -> None:
    end = bank + profile.boxes_per_bank * profile.box_size
    data[end] = checksum(data, bank, end)
    for i in range(profile.boxes_per_bank):
        start = bank + i * profile.box_size
        data[end + 1 + i] = checksum(data, start, start + profile.box_size)


def within(value: int, low: int, high: int, field: str) -> None:
    if not isinstance(value, int) or not low <= value <= high:
        raise InvalidSave(f"{field}须为 {low}–{high}。")


@dataclass(frozen=True)
class Layout:
    start: int
    capacity: int
    stride: int
    name_bytes: int = NAME_BYTES

    def mon(self, slot: int) -> int:
        return self.start + self.capacity + 2 + slot * self.stride

    def owner(self, slot: int) -> int:
        return self.mon(self.capacity) + self.name_bytes * slot

    def nickname(self, slot: int) -> int:
        return self.owner(self.capacity + slot)


@dataclass(frozen=True)
class Mon:
    species: int
    level: int
    experience: int
    nickname: str
    hp: int
    status: int
    moves: tuple[int, ...]
    pp: tuple[int, ...]
    pp_ups: tuple[int, ...]
    iv: tuple[int, ...]
    effort: tuple[int, ...]
    stats: tuple[int, ...]


@dataclass(frozen=True)
class Entry:
    id: int
    qty: int


class Save:
    def __init__(self, catalog: Catalog, raw: bytes, map_ids=None):
        preferred = JAPANESE if catalog.japanese else INTERNATIONAL
        self.profile = detect_profile(raw, preferred)
        self.catalog = catalog if catalog.japanese == self.profile.japanese else Catalog.reference(self.profile.japanese)
        self.map_ids = map_ids
        self.original = bytes(raw)
        self.data = bytearray(raw)
        self.validate()

    @property
    def current_box(self) -> int:
        return self.data[self.profile.box_number] & (BOX_INITIALIZED - 1)

    @property
    def initialized(self) -> bool:
        return bool(self.data[self.profile.box_number] & BOX_INITIALIZED)

    @property
    def player(self) -> str:
        return self.catalog.charset.decode(self.data[PLAYER:PLAYER + self.profile.name_bytes])

    @property
    def map_id(self) -> int:
        return self.data[self.profile.current_map]

    @property
    def dirty(self) -> bool:
        return self.original != self.data

    def layout(self, box: int | None) -> Layout:
        if box is None:
            return Layout(self.profile.party, 6, 44, self.profile.name_bytes)
        within(box, 0, self.profile.box_count - 1, "箱号")
        return Layout(self.profile.active_box if box == self.current_box else box_offset(box, self.profile),
                      self.profile.box_capacity, 33, self.profile.name_bytes)

    def count(self, box: int | None) -> int:
        layout = self.layout(box)
        if box is None or box == self.current_box or self.initialized:
            return self.data[layout.start]
        return 0

    def validate(self) -> None:
        data = self.data
        if len(data) != SAVE_SIZE:
            raise InvalidSave(f"存档为 {len(data):,} 字节，此 ROM 的 SRAM 存档须为 32,768 字节。")
        actual = checksum(data, PLAYER, self.profile.main_sum)
        if data[self.profile.main_sum] != actual:
            raise InvalidSave(f"主区校验错误。文件记录 {data[self.profile.main_sum]:02X}，从内容计算得到 {actual:02X}。")
        if self.map_ids is not None and self.map_id not in self.map_ids:
            raise InvalidSave(f"当前地图 ID {self.map_id:02X} 不在 ROM 的可用范围内。")
        player = data[PLAYER:PLAYER + self.profile.name_bytes]
        if player[0] in (0, 0x50) or self.catalog.charset.string_end(player) is None:
            raise InvalidSave("玩家名结构不完整。请先在游戏中使用「保存」。")
        within(self.current_box, 0, self.profile.box_count - 1, "当前箱号")
        self.validate_mons(None, "随身队伍")
        self.validate_mons(self.current_box, f"当前箱子 {self.current_box + 1}")
        for pc, label in ((False, "背包"), (True, "PC 道具")):
            start, capacity = (self.profile.pc_items, 50) if pc else (self.profile.bag, 20)
            count = data[start]
            if count > capacity or data[start + 1 + count * 2] != 255:
                raise InvalidSave(f"{label}的容量或列表结束标记有误。")
            for i, entry in enumerate(self.items(pc), 1):
                if entry.id not in self.catalog.items or not 1 <= entry.qty <= 99:
                    raise InvalidSave(f"{label}第 {i} 格包含无效道具 ID {entry.id:02X} 或数量 {entry.qty}。")
        if not self.initialized:
            return
        for bank in BOX_BANKS:
            end = bank + self.profile.boxes_per_bank * self.profile.box_size
            if data[end] != checksum(data, bank, end):
                raise InvalidSave(f"箱子存储区 {bank:04X} 的合计校验有误。")
            for i in range(self.profile.boxes_per_bank):
                box = i + (self.profile.boxes_per_bank if bank == BOX_BANKS[1] else 0)
                offset = box_offset(box, self.profile)
                if data[end + i + 1] != checksum(data, offset, offset + self.profile.box_size):
                    raise InvalidSave(f"箱子 {box + 1} 的独立校验有误。")
                if box != self.current_box:
                    self.validate_mons(box, f"箱子 {box + 1}")

    def validate_mons(self, box: int | None, label: str) -> None:
        layout = self.layout(box)
        count = self.data[layout.start]
        if count > layout.capacity or self.data[layout.start + 1 + count] != 255:
            raise InvalidSave(f"{label}的容量或种类列表结束标记有误。")
        for slot in range(count):
            start = layout.mon(slot)
            mon = self.data[start:start + layout.stride]
            species = mon[0]
            if species not in self.catalog.species or species != self.data[layout.start + 1 + slot]:
                raise InvalidSave(f"{label}第 {slot + 1} 格的种类 ID {species:02X} 无效或与列表不一致。")
            if any(move not in self.catalog.moves or move == 0xA5 for move in mon[8:12]):
                raise InvalidSave(f"{label}第 {slot + 1} 格包含无效招式 ID 或固定的「挣扎」。")
            if mon[4] not in STATUS:
                raise InvalidSave(f"{label}第 {slot + 1} 格的异常状态无效。")
            level = mon[33] if box is None else mon[3]
            if not 1 <= level <= 100:
                raise InvalidSave(f"{label}第 {slot + 1} 格等级 {level} 无效。")
            n = layout.nickname(slot)
            if not self.catalog.charset.valid_stored_name(self.data[n:n + self.profile.name_bytes]):
                raise InvalidSave(f"{label}第 {slot + 1} 格的昵称缺少有效结束符。")
            owner = layout.owner(slot)
            if not self.catalog.charset.valid_stored_name(self.data[owner:owner + self.profile.name_bytes]):
                raise InvalidSave(f"{label}第 {slot + 1} 格的训练家名称结构不完整。")

    def read_mon(self, box: int | None, slot: int) -> Mon:
        within(slot, 0, self.count(box) - 1, "精灵位置")
        layout = self.layout(box)
        offset = layout.mon(slot)
        name = layout.nickname(slot)
        raw = self.data[offset:offset + layout.stride]
        iv = (raw[27] >> 4, raw[27] & 15, raw[28] >> 4, raw[28] & 15)
        effort = tuple(int.from_bytes(raw[i:i + 2], "big") for i in range(17, 27, 2))
        exp = int.from_bytes(raw[14:17], "big")
        level = raw[33] if box is None else self.catalog.level(raw[0], exp)
        stats = (tuple(int.from_bytes(raw[i:i + 2], "big") for i in range(34, 44, 2)) if box is None
                 else self.catalog.stats(raw[0], level, iv, effort))
        return Mon(raw[0], level, exp, self.catalog.charset.decode(self.data[name:name + self.profile.name_bytes]),
                   int.from_bytes(raw[1:3], "big"), raw[4], tuple(raw[8:12]),
                   tuple(v & 63 for v in raw[29:33]), tuple(v >> 6 for v in raw[29:33]),
                   iv, effort, stats)

    def new_mon(self, species: int, level: int = 5) -> Mon:
        mon = self.catalog.species[species]
        iv = (8,) * 4
        effort = (0,) * 5
        stats = self.catalog.stats(species, level, iv, effort)
        moves = self.catalog.suggested_moves(species, level)
        nickname = self.catalog.default_nickname(species)
        return Mon(species, level, self.catalog.experience(species, level), nickname, stats[0], 0,
                   moves, tuple(self.catalog.base_pp[m] for m in moves), (0,) * 4, iv, effort, stats)

    def apply_mon(self, box: int | None, slot: int | None, mon: Mon) -> Mon:
        layout = self.layout(box)
        count = self.count(box)
        old = None
        if slot is None:
            if count >= layout.capacity:
                raise InvalidSave("目标已满。现有精灵没有被替换。")
            slot = count
        else:
            old = self.read_mon(box, slot)
            if old == mon:
                return old
        mon, nick = self.prepare_mon(box, mon, old)
        return self.write_mon(box, slot, mon, nick, old is None)

    def prepare_mon(self, box: int | None, mon: Mon, old: Mon | None) -> tuple[Mon, bytes | None]:
        if mon.species not in self.catalog.species:
            raise InvalidSave("精灵 ID 不在此版本的 151 种有效精灵中。")
        within(mon.level, 1, 100, "等级")
        for iv in mon.iv:
            within(iv, 0, 15, "个体值")
        for effort in mon.effort:
            within(effort, 0, 65535, "努力值")
        if mon.status not in STATUS:
            raise InvalidSave("异常状态值无效。")
        seen = set()
        empty = False
        for i, (move, pp, ups) in enumerate(zip(mon.moves, mon.pp, mon.pp_ups, strict=True), 1):
            try:
                rule, reason = self.catalog.move_rule(mon.species, mon.level, move)
            except KeyError:
                raise InvalidSave(f"招式 {i} 的 ID 无效。") from None
            if rule == "disabled":
                raise InvalidSave(reason)
            if not move:
                empty = True
            elif empty or move in seen:
                raise InvalidSave("招式从第一格连续填写，同一招式只能占一格。")
            seen.add(move)
            within(ups, 0, 3 if move else 0, f"招式 {i} 的 PP 提升次数")
            within(pp, 0, self.catalog.max_pp(move, ups), f"招式 {i} 的当前 PP")
        if not mon.moves[0]:
            raise InvalidSave("至少保留一个招式，以便游戏建立战斗招式菜单。")
        exp = self.catalog.experience(mon.species, mon.level)
        if (old and mon.level == old.level and mon.species == old.species
                and exp <= old.experience <= self.catalog.experience(mon.species, 100)
                and self.catalog.level(mon.species, old.experience) == mon.level):
            exp = old.experience
        stats = mon.stats if box is None else self.catalog.stats(mon.species, mon.level, mon.iv, mon.effort)
        if box is None:
            exact = self.catalog.stats(mon.species, mon.level, mon.iv, mon.effort)
            for i, value in enumerate(stats):
                if (old and old.stats[i] == value) or value == exact[i]:
                    continue
                lo = 16 if i in (2, 4) else (1 if i == 0 else 5)
                hi = 511 if i in (2, 4) else 999
                within(value, lo, hi, f"{'最大 ' if i == 0 else ''}{STAT_NAMES[i]}")
        within(mon.hp, 0, stats[0], "当前 HP")
        if mon.hp == 0 and mon.status:
            raise InvalidSave("濒死精灵的异常状态须选「正常」。")
        if box is None and stats[0] != exact[0]:
            # Vitamins and PC transfers recalculate max HP without changing
            # current HP. Level-ups instead add the max-HP difference.
            same_hp_inputs = old and (old.species, old.level, old.iv, old.effort[0], old.hp, old.stats[0]) == (
                mon.species, mon.level, mon.iv, mon.effort[0], mon.hp, stats[0])
            if not same_hp_inputs:
                if mon.hp > exact[0]:
                    raise InvalidSave(f"当前 HP 超过公式上限 {exact[0]}，游戏重算后会超出最大 HP。")
                if mon.level < 100:
                    next_hp = self.catalog.stats(mon.species, mon.level + 1, mon.iv, mon.effort)[0]
                    if stats[0] - mon.hp > next_hp:
                        raise InvalidSave("手填最大 HP 与当前 HP 的差距会使游戏升级时的 HP 溢出。")
        raw_name = None if old and old.nickname == mon.nickname else self.catalog.charset.nickname(mon.nickname)
        return replace(mon, experience=exp, stats=stats), raw_name

    def write_mon(self, box: int | None, slot: int, mon: Mon, nick: bytes | None, adding: bool) -> Mon:
        layout = self.layout(box)
        previous = self.data
        data = bytearray(previous)
        other_box = box is not None and box != self.current_box
        if other_box and not self.initialized:
            for b in range(self.profile.box_count):
                start = box_offset(b, self.profile)
                data[start:start + 2] = b"\x00\xff"
            data[self.profile.box_number] |= BOX_INITIALIZED
            for bank in BOX_BANKS:
                bank_checksum(data, bank, self.profile)
        offset = layout.mon(slot)
        raw = bytearray(layout.stride) if adding else data[offset:offset + layout.stride]
        species = self.catalog.species[mon.species]
        if raw[0] != mon.species:
            raw[0] = mon.species
            raw[5:8] = species.types + bytes((species.catch_rate,))
        raw[1:3] = mon.hp.to_bytes(2, "big")
        if adding or (box is None and raw[33] != mon.level) or (
                box is not None and self.catalog.level(raw[0], int.from_bytes(raw[14:17], "big")) != mon.level):
            raw[3] = mon.level
        raw[4] = mon.status
        raw[8:12] = bytes(mon.moves)
        if adding:
            raw[12:14] = data[self.profile.player_id:self.profile.player_id + 2]
            owner = layout.owner(slot)
            data[owner:owner + self.profile.name_bytes] = data[PLAYER:PLAYER + self.profile.name_bytes]
        raw[14:17] = mon.experience.to_bytes(3, "big")
        for i, value in enumerate(mon.effort):
            raw[17 + i * 2:19 + i * 2] = value.to_bytes(2, "big")
        raw[27:29] = bytes((mon.iv[0] << 4 | mon.iv[1], mon.iv[2] << 4 | mon.iv[3]))
        raw[29:33] = bytes(pp | (up << 6) for pp, up in zip(mon.pp, mon.pp_ups))
        if box is None:
            raw[33] = mon.level
            for i, value in enumerate(mon.stats):
                raw[34 + i * 2:36 + i * 2] = value.to_bytes(2, "big")
        data[offset:offset + layout.stride] = raw
        data[layout.start + 1 + slot] = mon.species
        if adding:
            data[layout.start] += 1
            data[layout.start + 2 + slot] = 255
        if nick is not None:
            name_offset = layout.nickname(slot)
            data[name_offset:name_offset + self.profile.name_bytes] = nick
        if other_box:
            bank_checksum(data, BOX_BANKS[box // self.profile.boxes_per_bank], self.profile)
        self.commit(data)
        return mon

    def items(self, pc: bool) -> list[Entry]:
        start = self.profile.pc_items if pc else self.profile.bag
        return [Entry(self.data[i], self.data[i + 1])
                for i in range(start + 1, start + 1 + self.data[start] * 2, 2)]

    def item_rule(self, pc: bool, entries: list[Entry], item_id: int, qty: int) -> tuple[str, str]:
        item = self.catalog.items.get(item_id)
        if item is None:
            return "disabled", "道具 ID 未定义或用作内部菜单编号。"
        if item.disabled:
            return "disabled", item.disabled
        if qty < 1 or qty > 99:
            return "disabled", "每组数量须在 1–99。"
        same = sum(e.qty for e in (*entries, *self.items(not pc)) if e.id == item_id)
        if item.key and (qty != 1 or same):
            return "disabled", "关键道具和秘传学习器仅保留一份，以免重复触发或卡住脚本。"
        if item_id in ITEM_UNUSUAL:
            return "unusual", ITEM_UNUSUAL[item_id]
        if same + qty > 1 and item_id in ITEM_UNIQUE:
            return "unusual", "超过此版本常规流程可以取得的数量。"
        if item_id in QUEST_ITEMS:
            return "normal", QUEST_ITEMS[item_id]
        return "normal", "此道具允许写入。"

    def apply_items(self, pc: bool, index: int | None, entry: Entry | None) -> None:
        entries = self.items(pc)
        start, capacity = (self.profile.pc_items, 50) if pc else (self.profile.bag, 20)
        old = None
        if index is not None:
            within(index, 0, len(entries) - 1, "道具位置")
            old = entries.pop(index)
        elif len(entries) >= capacity:
            raise InvalidSave("目标已满。请腾出一格后再添加。")
        if old == entry:
            return
        if old and (entry is None or entry.id != old.id):
            has_another = any(e.id == old.id for e in (*entries, *self.items(not pc)))
            parcel_needed = old.id == 0x46 and not self.data[self.profile.event_flags + 7] & 1
            if not has_another and (old.id in BLOCK_FINITE_ITEMS or parcel_needed):
                raise InvalidSave("此关键道具关系到剧情通路或只能领取一次，移除最后一份可能使流程中断。")
        if entry:
            state, reason = self.item_rule(pc, entries, entry.id, entry.qty)
            if state == "disabled":
                raise InvalidSave(reason)
            entries.insert(len(entries) if index is None else index, entry)
        data = bytearray(self.data)
        raw = bytes(field for item in entries for field in (item.id, item.qty))
        data[start:start + len(raw) + 2] = bytes((len(entries),)) + raw + b"\xff"
        self.commit(data)

    def clear_flags(self, flags: tuple[tuple[int, int], ...]) -> bool:
        data = bytearray(self.data)
        for offset, mask in flags:
            data[offset] &= ~mask
        if data == self.data:
            return False
        self.commit(data)
        return True

    def set_bytes(self, changes):
        data = bytearray(self.data)
        for offset, value in changes:
            within(offset, PLAYER, self.profile.main_sum - 1, "主区偏移")
            within(value, 0, 255, "字节值")
            data[offset] = value
        if data == self.data:
            return False
        self.commit(data)
        return True

    def commit(self, data: bytearray) -> None:
        data[self.profile.main_sum] = checksum(data, PLAYER, self.profile.main_sum)
        old = self.data
        self.data = data
        try:
            self.validate()
        except Exception:
            self.data = old
            raise
