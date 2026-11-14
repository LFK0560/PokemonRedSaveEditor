from collections import Counter
from dataclasses import dataclass, replace
import re

from .maps import Area, Atlas, Object
from .rom import rom_address, save_address, word
from .save import EVENT_FLAGS, InvalidSave, Save


TOGGLE_FLAGS = save_address(0xD5A6)
HIDDEN_FLAGS = save_address(0xD6F0)
DEFAULT_END = 0x328A
TALK_TO_TRAINER = b"\xcd\xe1\x31\xc3\xec\x24"

CATEGORIES = {"fixed": "固定精灵", "trainer": "普通训练家", "leader": "馆主",
              "npc": "NPC", "item": "可见道具", "hidden": "隐藏道具"}
NPC_NAMES = (
    "居民 主角 劲敌 大木博士 少年 宝可梦 女训练家 男训练家 小女孩 鸟 中年男子 赌徒 理科男 女孩 登山者 美女 绅士 茉莉 "
    "骑手 水手 厨师 自行车店店员 富士老人 坂木 火箭队 祈祷师 服务员 西尔佛员工 中年女子 少女 阿渡 科学家 科学家 "
    "摇滚乐手 游泳者 狩猎区员工 道馆向导 老爷爷 店员 钓鱼达人 老奶奶 乔伊 通信接待员 社长 西尔佛员工 园长 船长 "
    "钓鱼者 阿桔 警卫 警卫 妈妈 男子 小男孩 玩家 玩家 宝可梦 菊子 希巴 科拿 小海狮 精灵球 化石 岩石 纸张 图鉴 "
    "告示牌 卡比兽 琥珀 秘密琥珀 赌徒 赌徒 睡觉的老人"
).split()
TRAINER_NAMES = (
    "训练家 短裤小子 捕虫少年 迷你裙 水手 男初级训练家 女初级训练家 怪兽狂 理科男 登山者 骑手 小偷 工程师 杂耍者 "
    "钓鱼者 游泳者 暴走族 赌徒 美女 超能力者 摇滚乐手 杂耍者 驯兽师 养鸟人 空手道王 劲敌 大木博士 首领 科学家 坂木 "
    "火箭队 男精英训练家 女精英训练家 希巴 小刚 小霞 马志士 莉佳 阿桔 夏伯 娜姿 绅士 劲敌 冠军 科拿 祈祷师 菊子 阿渡"
).split()

LEADERS = {
    0x2D: ("坂木", 0x51, "绿色徽章、TM27 和常青道馆剧情。"),
    0x36: ("小刚", 0x77, "灰色徽章和 TM34。"),
    0x41: ("小霞", 0xBF, "蓝色徽章和 TM11。"),
    0x5C: ("马志士", 0x167, "橙色徽章和 TM24。"),
    0x86: ("莉佳", 0x1A9, "彩虹徽章和 TM21。"),
    0x9D: ("阿桔", 0x259, "粉红徽章和 TM06。"),
    0xA6: ("夏伯", 0x299, "深红徽章和 TM38。"),
    0xB2: ("娜姿", 0x361, "金色徽章和 TM46。"),
}
STORY = {
    (0x00, 1): ("大木博士", "触发跟随大木博士到研究所的开场剧情。", 0),
    (0x01, 5): ("挡路的老人", "显隐与包裹剧情及常青市通路共用。", 0x38),
    (0x01, 7): ("捕捉教学老人", "教学和离开常青市的状态由剧情管理。", 0x38),
    (0x02, 3): ("博物馆向导", "脚本会移动玩家或改变向导的剧情状态。", None),
    (0x02, 5): ("道馆向导", "引导或挡路脚本与道馆进度关联。", None),
    (0x03, 1): ("劲敌", "对战结算会推进华蓝市剧情并隐藏对象。", 0x98),
    (0x03, 2): ("火箭队小偷", "重战会影响遭破坏的民居剧情及 TM28 奖励。", 0xA7),
    (0x17, 1): ("卡比兽 · 30 级", "复位会在原地重新堵住 12 号道路。", 0x48F),
    (0x1B, 7): ("卡比兽 · 30 级", "复位会在原地重新堵住 16 号道路。", 0x4C9),
    (0x21, 1): ("劲敌（早期）", "对战发生在特定徽章阶段，复位需回退通路剧情。", None),
    (0x21, 2): ("劲敌（后期）", "对战发生在特定徽章阶段，复位需回退通路剧情。", None),
    (0x23, 1): ("金珠桥的火箭队员", "金珠发放、挑战与退场共用同一段桥上剧情。", 0x540),
    (0x27, 1): ("茉莉（坐着）", "对话会发放城镇地图，场景脚本还会切换她的位置。", 0x18),
    (0x27, 2): ("茉莉（走动）", "同一个角色的另一种位置，由场景脚本切换。", None),
    (0x27, 3): ("城镇地图", "仅作剧本道具展示，领取由茉莉的对话控制。", 0x18),
    (0x28, 1): ("劲敌", "对战结算会推进选择初始精灵的剧情。", 0x23),
    (0x28, 2): ("小火龙的精灵球", "三选一脚本会改变玩家和劲敌的初始精灵。", 0x22),
    (0x28, 3): ("杰尼龟的精灵球", "三选一脚本会改变玩家和劲敌的初始精灵。", 0x22),
    (0x28, 4): ("妙蛙种子的精灵球", "三选一脚本会改变玩家和劲敌的初始精灵。", 0x22),
    (0x28, 5): ("大木博士", "脚本会发放初始精灵和图鉴，并修改开场流程。", None),
    (0x28, 6): ("图鉴", "移除或恢复由发放图鉴的剧情控制。", 0x25),
    (0x28, 7): ("图鉴", "移除或恢复由发放图鉴的剧情控制。", 0x25),
    (0x28, 8): ("大木博士", "显隐由研究所主线脚本控制。", None),
    (0x34, 1): ("售票员", "门票旗标关联付款和室内通路。", 0x68),
    (0x34, 5): ("秘密琥珀", "显隐与馆员交付秘密琥珀的剧情关联。", 0x69),
    (0x3D, 1): ("化石研究员", "对战后才开放化石二选一。重战可能重开选择。", None),
    (0x3D, 6): ("甲壳化石", "二选一奖励，共用化石选择和通路旗标。", None),
    (0x3D, 7): ("贝壳化石", "二选一奖励，共用化石选择和通路旗标。", None),
    (0x42, 1): ("自行车店店员", "脚本会消费兑换券并发放自行车。", 0xC0),
    (0x58, 1): ("正辉（变身）", "关联传送机、正辉的形态和一次性船票。", 0x55C),
    (0x58, 2): ("正辉", "关联传送机、正辉的形态和一次性船票。", 0x55C),
    (0x58, 3): ("正辉（另一位置）", "关联传送机、正辉的形态和一次性船票。", 0x55C),
    (0x5A, 5): ("宝可梦俱乐部会长", "再次触发会发放自行车兑换券。", 0x151),
    (0x60, 2): ("船上的劲敌", "对战入口和船程状态由特定剧情阶段管理。", None),
    (0x65, 1): ("圣特安努号船长", "一次性发放 HM01，同时推进开船条件。", 0x5E0),
    (0x78, 1): ("冠军劲敌", "重战会重走冠军结算和名人堂流程。", None),
    (0x84, 2): ("伊布（礼物）", "由赠送精灵的脚本管理，复位会再次发放一次性礼物。", None),
    (0x87, 11): ("海报前的火箭队员", "对战和退场决定火箭队基地入口是否可用。", None),
    (0x8A, 5): ("代币盒赠送者", "再次触发会发放一次性代币盒。", 0x1E0),
    (0x8F, 1): ("塔内劲敌", "战后退场和塔内剧情共用旗标。", 0xEF),
    (0x94, 4): ("富士老人（塔内）", "救援会结束塔内剧情并传送玩家。", 0x117),
    (0x95, 5): ("富士老人", "首次对话会发放宝可梦之笛。", 0x128),
    (0x9B, 1): ("狩猎区园长", "交付金假牙会发放一次性 HM04。", 0x238),
    (0xB1, 1): ("空手道大王", "战后解锁两只礼物精灵的选择。", None),
    (0xB1, 6): ("飞腿郎（礼物）", "二选一礼物，共用格斗道场的领取状态。", 0x356),
    (0xB1, 7): ("快拳郎（礼物）", "二选一礼物，共用格斗道场的领取状态。", 0x357),
    (0xB7, 1): ("超能力者", "首次对话会发放 TM29。", 0x3B0),
    (0xC7, 5): ("楼梯旁的火箭队员", "此训练家的状态还控制秘密楼梯的剧情。", 0x675),
    (0xCA, 1): ("坂木（火箭队基地）", "战后退场和西尔佛检视镜显隐由同一个剧情流程控制。", 0x6A7),
    (0xCA, 2): ("坂木门前的火箭队员（左）", "两名守卫的完成位同时控制通向坂木的门。", 0x6A2),
    (0xCA, 3): ("坂木门前的火箭队员（右）", "两名守卫的完成位同时控制通向坂木的门。", 0x6A3),
    (0xCA, 4): ("电梯钥匙旁的火箭队员", "战后对话会设置电梯钥匙掉落旗标并显示钥匙，影响基地通行。", 0x6A4),
    (0xDE, 1): ("秘密小屋管理员", "首次对话会发放一次性 HM03。", 0x880),
    (0xEB, 1): ("西尔佛公司社长", "再次触发会发放一次性大师球。", 0x78D),
    (0xEB, 3): ("坂木（西尔佛公司）", "击败后改变公司和金黄市的剧情通路。", None),
}
FIXED_SCRIPTS = {
    0x53: (0xD663, 0x469, "PowerPlant / EndTrainerBattle"),
    0xE3: (0xD650, 0x8C1, "CeruleanCaveB1F / EndTrainerBattle"),
    0xA2: (0xD668, 0x9DA, "SeafoamIslandsB4F / EndTrainerBattle"),
}
QUEST_FLAGS = {
    0x05: (0x18, "已领取城镇地图"), 0x06: (0xC0, "已兑换自行车"),
    0x1F: (0x69, "已领取秘密琥珀"),
    0x29: (0x57E, "已领取甲壳化石"), 0x2A: (0x57F, "已领取贝壳化石"),
    0x2D: (0x151, "已领取兑换券"),
    0x3F: (0x55C, "已领取船票"), 0x40: (0x239, "已交付金假牙"),
    0x45: (0x1E0, "已领取代币盒"), 0x46: (0x38, "已交付包裹"),
    0x49: (0x128, "已领取宝可梦之笛"),
    0xC4: (0x5E0, "已领取 HM01"), 0xC5: (0x4CE, "已领取 HM02"),
    0xC6: (0x880, "已领取 HM03"), 0xC7: (0x238, "已领取 HM04"),
    0xC8: (0x3D8, "已领取 HM05"),
}


def flag(address: int, bit: int) -> tuple[int, int]:
    return address + bit // 8, 1 << (bit % 8)


def in_save(save: Save, bit: tuple[int, int]) -> bool:
    return bool(save.data[bit[0]] & bit[1])


@dataclass(frozen=True)
class Event:
    map_id: int
    id: str
    x: int
    y: int
    sprite: int
    name: str
    kind: str
    flags: tuple[tuple[int, int], ...] = ()
    observed: tuple[tuple[int, int], ...] = ()
    idle_at: int | None = None
    disabled: str = ""
    evidence: str = ""
    cooperative: bool = False
    requires_clear: tuple[tuple[int, int], ...] = ()

    @property
    def key(self) -> tuple[int, str]:
        return self.map_id, self.id

    def status(self, save: Save | None) -> str:
        if self.cooperative:
            return "可重复互动"
        if not save:
            return "导入存档后查看"
        if any(in_save(save, bit) for bit in self.requires_clear):
            return "通路已关闭"
        bits = self.flags or self.observed
        if not bits:
            return "状态待验证" if "待验证" in self.disabled else "无法安全复位"
        if self.flags and self.idle_at is not None and save.data[self.idle_at]:
            return "地图脚本执行中"
        on = [in_save(save, f) for f in bits]
        if self.flags and len(on) > 1 and len(set(on)) > 1:
            return "旗标状态不一致"
        if self.disabled:
            return "已完成 · 无法安全复位" if any(on) else "未完成 · 无法安全复位"
        return "已完成" if any(on) else "可触发"

    def can_reset(self, save: Save | None) -> bool:
        return bool(self.flags and not self.disabled and self.status(save) == "已完成")

    def reset(self, save: Save) -> bool:
        if self.flags and not self.disabled and self.status(save) == "可触发":
            return False
        if not self.can_reset(save):
            raise InvalidSave(self.disabled or f"当前状态为「{self.status(save)}」，无法安全复位。")
        return save.clear_flags(self.flags)


class EventIndex:
    def __init__(self, atlas: Atlas):
        self.atlas = atlas
        self.rom = atlas.rom
        self.toggles = self.read_toggles()
        self.hidden_items = self.read_hidden_items()
        self.by_map = {a.id: self.area_events(a) for a in atlas.areas.values()}
        self.by_key = {event.key: event for events in self.by_map.values() for event in events}

    def read_toggles(self):
        states = {}
        cursor = 0xCAD8
        index = 0
        while self.rom[cursor] != 255:
            map_id, obj_id, initial = self.rom[cursor:cursor + 3]
            states[map_id, obj_id] = (flag(TOGGLE_FLAGS, index), initial)
            cursor += 3
            index += 1
        return states

    def read_hidden_items(self):
        rom = self.rom
        functions = {}
        for i, map_id in enumerate(rom[0x46A3A:0x46A8F]):
            cursor = rom_address(0x11, word(rom, 0x46A90 + i * 2))
            while rom[cursor] != 255:
                y, x, item, bank = rom[cursor:cursor + 4]
                if rom_address(bank, word(rom, cursor + 4)) == 0x76687:
                    functions[map_id, x, y] = item
                cursor += 6
        result = []
        cursor = 0x766B7
        while rom[cursor] != 255:
            map_id, y, x = rom[cursor:cursor + 3]
            index = (cursor - 0x766B7) // 3
            cursor += 3
            if map_id not in self.atlas.areas:
                continue
            item = functions.pop((map_id, x, y), None)
            result.append((map_id, index, x, y, item))
        for (map_id, x, y), item in functions.items():
            if map_id in self.atlas.areas:
                result.append((map_id, None, x, y, item))
        return result

    def area_events(self, area: Area) -> tuple[Event, ...]:
        result = [self.object_event(area, obj) for obj in area.objects]
        result.extend(self.hidden_event(map_id, index, x, y, item)
                      for map_id, index, x, y, item in self.hidden_items if map_id == area.id)
        if area.id == 0x93:
            result.append(Event(area.id, "S-Marowak", 9, 16, 5, "嘎啦嘎啦的幽灵", "fixed",
                                observed=(flag(EVENT_FLAGS, 0x10F),),
                                disabled="驱散幽灵会开放去 7F 的楼梯，复位会回退宝可梦塔的剧情通路。",
                                evidence="PokemonTower6F / EVENT_BEAT_GHOST_MAROWAK"))
        if area.group == "SS_ANNE":
            result = [replace(e, requires_clear=(flag(EVENT_FLAGS, 0x5E2),),
                              evidence=e.evidence + " / VermilionDock: 船尚未离港")
                      if e.flags else e for e in result]
        return tuple(result)

    def object_event(self, area: Area, obj: Object) -> Event:
        a = area.id
        key = (a, obj.id)
        event = Event(a, str(obj.id), obj.x, obj.y, obj.sprite, f"对象 {obj.id}", obj.kind)
        hide, initial = self.toggles.get(key, (None, None))
        leader = LEADERS.get(a) if obj.id == 1 else None
        if leader:
            name, complete, reward = leader
            return replace(event, name=f"{name}（馆主）", kind="leader", observed=(flag(EVENT_FLAGS, complete),),
                           disabled=f"馆主结算关联{reward}",
                           evidence=f"地图 {a:02X} 馆主脚本 / EVENT {complete:03X}")
        if key in STORY:
            name, reason, complete = STORY[key]
            kind = "fixed" if obj.sprite == 0x43 else obj.kind
            observed = (flag(EVENT_FLAGS, complete),) if complete is not None else ((hide,) if hide else ())
            return replace(event, name=name, kind=kind, observed=observed, disabled=reason,
                           evidence=f"{area.key} 脚本 {obj.script:06X}")
        if obj.kind == "fixed":
            return self.fixed_event(area, obj, event, hide, initial)
        if obj.kind == "trainer":
            return self.trainer_event(area, obj, event, hide)
        if obj.kind == "item":
            item = self.atlas.catalog.items.get(obj.value)
            name = item.name if item else f"道具 {obj.value:02X}"
            if item and (item.key or item.disabled):
                reason = "该道具用于剧情、秘传学习器或占位，重复恢复可能改变通行或一次性领取状态。"
                return replace(event, name=name, disabled=reason, observed=(hide,) if hide else (),
                               evidence=f"{area.key} 对象数据 / PickUpItem")
            if obj.script == 0x2509 and initial == 0x15 and item:
                return replace(event, name=name, flags=(hide,),
                               evidence=f"ROM 文本入口 00:2509 → PickUpItem 01:4CE8 / 显隐表 03:4AD8")
            return replace(event, name=name, disabled="复位规则待验证。缺少独立拾取脚本或可见位。",
                           observed=(hide,) if hide else ())
        name = NPC_NAMES[obj.sprite] if obj.sprite < len(NPC_NAMES) else event.name
        if hide:
            return replace(event, name=name, disabled="复位规则待验证。显隐由地图剧情调度。",
                           observed=(hide,), evidence=f"{area.key} / 显隐表 03:4AD8")
        if obj.sprite == 0x3F:
            return replace(event, name="可推动岩石", disabled="岩石和机关影响通路，由地图脚本处理。")
        if (obj.sprite in (0x26, 0x29, 0x2A, 0x24) and a not in (0x87, 0x8A)
                or self.is_plain_text(obj.script)):
            return replace(event, name=name, cooperative=True, disabled="此对象可重复互动。",
                           evidence=f"{area.key} 文本入口 {obj.script:06X}")
        return replace(event, name=name, disabled="复位规则待验证。此对象调用专用脚本。",
                       evidence=f"{area.key} 文本入口 {obj.script:06X}")

    def is_plain_text(self, start: int) -> bool:
        rom = self.rom
        if start < 0 or rom[start] != 0x17:
            return False
        index = start
        for _ in range(8):
            if rom[index] != 0x17:
                return rom[index] == 0x50
            bank = rom[index + 3]
            text = rom_address(bank, word(rom, index + 1))
            # A text_far entry may start with native code. Require a literal
            # text entry and a terminated chain of far-text pointers.
            if rom[text] != 0:
                return False
            index += 4
        return False

    def header_flag(self, area: Area, at: int, obj_id: int) -> tuple[int, int] | None:
        if at < 0 or self.rom[at] != obj_id:
            return None
        wr = word(self.rom, at + 2)
        bit = save_address(wr) + obj_id // 8
        return flag(save_address(wr), obj_id) if EVENT_FLAGS <= bit < EVENT_FLAGS + 320 else None

    def fixed_event(self, area: Area, obj: Object, event: Event, hide, initial) -> Event:
        info = self.atlas.catalog.species.get(obj.value)
        name = (info.name if info else f"精灵 {obj.value:02X}") + f" · {obj.level} 级"
        base = replace(event, name=name, observed=(hide,) if hide else ())
        if area.id == 0xC2:
            return replace(base, observed=(flag(EVENT_FLAGS, 0x53E),),
                           disabled="该地图战后重载脚本会清除 1F 巨石机关旗标，可能改变既有通路。",
                           evidence="VictoryRoad2F / VictoryRoad2FResetBoulderEventScript")
        if area.id not in FIXED_SCRIPTS or initial != 0x15 or not info:
            return replace(base, disabled="复位规则待验证。")
        wr_idle, bit, evidence = FIXED_SCRIPTS[area.id]
        offset = obj.script
        rom = self.rom
        header_object = 2 if area.id == 0xA2 else obj.id
        battle = self.header_flag(area, rom_address(area.bank, word(rom, offset + 2)), header_object)
        expected = flag(EVENT_FLAGS, bit + (obj.id - 9 if area.id == 0x53 else 0))
        if rom[offset:offset + 2] != b"\x08\x21" or battle != expected:
            return replace(base, disabled="复位规则待验证。战斗标记与核对的脚本不一致。")
        return replace(base, flags=(hide, battle), observed=(), idle_at=save_address(wr_idle),
                       evidence=f"{evidence} / 对象脚本 {offset:06X}")

    def trainer_event(self, area: Area, obj: Object, event: Event, hide) -> Event:
        index = obj.value - 200
        name = TRAINER_NAMES[index] if index < len(TRAINER_NAMES) else "训练家"
        event = replace(event, name=f"{name}（对象 {obj.id}）")
        if area.id in (0x6C, 0xC2, 0xC6):
            reason = "战后会重载冠军之路并可能清除其他楼层的巨石机关旗标。"
        elif area.id in (0x71, 0x78, 0xF5, 0xF6, 0xF7) or index in (25, 29, 33, 42, 43, 44, 46, 47):
            reason = "战斗结算会推进劲敌、组织首领或联盟流程。"
        elif area.id == 0xA6:
            reason = "答题机与训练家共享完成位，清位会改写道馆出题和开门状态。"
        elif hide:
            reason = "复位规则待验证。剧情会切换此训练家的显隐。"
        else:
            reason = ""
        rom = self.rom
        p = obj.script
        if p < 0 or rom[p:p + 2] != b"\x08\x21":
            return replace(event, disabled=reason or "复位规则待验证。该对战使用专用脚本。")
        header = rom_address(area.bank, word(rom, p + 2))
        battle = self.header_flag(area, header, obj.id)
        if not battle:
            return replace(event, disabled=reason or "复位规则待验证。战斗标记未能绑定。")
        event = replace(event, observed=(battle,), evidence=f"{area.key} / 对战头 {header:06X}")
        if reason:
            return replace(event, disabled=reason)
        # Require the direct TalkToTrainer wrapper (some maps share its tail)
        # and verify that the map dispatcher really uses the common settlement.
        tail = p + 4
        if rom[tail] == 0x18:
            tail += 2 + (rom[tail + 1] - (256 if rom[tail + 1] >= 128 else 0))
        if rom[tail:tail + 6] != TALK_TO_TRAINER:
            return replace(event, disabled="复位规则待验证。对话入口会执行附加脚本。")
        for field in (4, 6, 8, 10):
            text = rom_address(area.bank, word(rom, header + field))
            if not self.is_plain_text(text):
                return replace(event, disabled="复位规则待验证。战斗对话头绑定了非纯文本脚本。")
        start = area.script
        dispatch = re.search(rb"\x11(..)\xfa(..)\xcd\x75\x31\xea\2\xc9", rom[start:start + 64], re.S)
        if dispatch:
            table = rom_address(area.bank, int.from_bytes(dispatch[1], "little"))
            # Examine only the table's battle end entry for the common battle route.
            if word(rom, table + 4) == DEFAULT_END:
                idle = save_address(int.from_bytes(dispatch[2], "little"))
                return replace(event, flags=(battle,), observed=(), idle_at=idle,
                               evidence=event.evidence + " / TalkToTrainer 00:31E1 / EndTrainerBattle 00:328A")
        return replace(event, disabled="复位规则待验证。该地图使用专用的对战结算。")

    def hidden_event(self, map_id, index, x, y, item):
        found = self.atlas.catalog.items.get(item)
        name = f"隐藏道具 · {found.name}" if found else "隐藏道具"
        event = Event(map_id, f"H{index}" if index is not None else f"H{x},{y}", x, y, 0, name, "hidden",
                      evidence="HiddenItems 1D:6687 / HiddenItemCoords 1D:66B7")
        if index is None or not found or found.key or found.disabled:
            return replace(event, disabled="复位规则待验证。坐标表或拾取脚本没有匹配的独立道具位。")
        bit = flag(HIDDEN_FLAGS, index)
        if (map_id, x, y) == (0x9C, 10, 1):
            return replace(event, observed=(bit,), disabled="道具坐标在原版房间外，游戏中无法到达。")
        return replace(event, flags=(bit,))

    def counts(self):
        return Counter((e.kind, "enabled" if e.flags else "repeat" if e.cooperative else
                        "unverified" if "待验证" in e.disabled else "disabled")
                       for e in self.by_key.values())
