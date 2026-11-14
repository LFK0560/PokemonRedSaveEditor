"""Build the hand-labelled map index from pret/pokered's map constants.

The program reads tile, warp, text and object data from the selected ROM.
Run with the pret source directory as the only argument.
"""
import json
from pathlib import Path
import re
import sys


TOWNS = {
    "PALLET_TOWN": "真新镇", "VIRIDIAN_CITY": "常青市", "PEWTER_CITY": "深灰市",
    "CERULEAN_CITY": "华蓝市", "LAVENDER_TOWN": "紫苑镇", "VERMILION_CITY": "枯叶市",
    "CELADON_CITY": "玉虹市", "FUCHSIA_CITY": "浅红市", "CINNABAR_ISLAND": "红莲岛",
    "INDIGO_PLATEAU": "石英高原", "SAFFRON_CITY": "金黄市",
}
CITY_PREFIXES = {k.rsplit("_", 1)[0]: v for k, v in TOWNS.items()}

GROUPS = {
    "REDS_HOUSE": "主角家", "MUSEUM": "深灰科学博物馆", "MT_MOON": "月见山",
    "ROCK_TUNNEL": "岩山隧道", "SS_ANNE": "圣特安努号", "VICTORY_ROAD": "冠军之路",
    "CELADON_MART": "玉虹百货公司", "CELADON_MANSION": "玉虹公寓",
    "POKEMON_TOWER": "宝可梦塔", "SEAFOAM_ISLANDS": "双子岛",
    "POKEMON_MANSION": "宝可梦屋", "SILPH_CO": "西尔佛公司",
    "COPYCATS_HOUSE": "模仿少女家", "ROCKET_HIDEOUT": "火箭队基地",
    "CERULEAN_CAVE": "华蓝洞窟",
    **{f"ROUTE_{i}_GATE": f"{i} 号道路关卡" for i in (11, 12, 15, 16, 18)},
}
FLOORS = {
    "ELEVATOR": "电梯", "ROOF": "屋顶", "ROOF_HOUSE": "屋顶小屋", "BOW": "船头",
    "KITCHEN": "厨房", "CAPTAINS_ROOM": "船长室", "1F_ROOMS": "1F 客舱",
    "2F_ROOMS": "2F 客舱", "B1F_ROOMS": "B1F 客舱",
}

SPECIAL = {
    "BLUES_HOUSE": "劲敌家", "OAKS_LAB": "大木博士研究所", "DAYCARE": "培育屋",
    "POWER_PLANT": "无人发电厂", "BIKE_SHOP": "自行车店", "BILLS_HOUSE": "正辉的家",
    "POKEMON_FAN_CLUB": "宝可梦俱乐部", "VERMILION_DOCK": "枯叶港",
    "UNDERGROUND_PATH_NORTH_SOUTH": "地下通道（南北）",
    "UNDERGROUND_PATH_WEST_EAST": "地下通道（东西）",
    "LANCES_ROOM": "四天王 · 阿渡", "LORELEIS_ROOM": "四天王 · 科拿",
    "BRUNOS_ROOM": "四天王 · 希巴", "AGATHAS_ROOM": "四天王 · 菊子",
    "HALL_OF_FAME": "名人堂", "CHAMPIONS_ROOM": "冠军房间",
    "GAME_CORNER": "玉虹游戏城", "GAME_CORNER_PRIZE_ROOM": "游戏城奖品兑换处",
    "MR_FUJIS_HOUSE": "富士老人家", "WARDENS_HOUSE": "狩猎区园长家",
    "FIGHTING_DOJO": "格斗道场", "MR_PSYCHICS_HOUSE": "超能力者的家",
    "NAME_RATERS_HOUSE": "姓名鉴定师家", "COLOSSEUM": "通信对战室",
    "TRADE_CENTER": "通信交换室", "DIGLETTS_CAVE": "地鼠洞穴",
    "MT_MOON_POKECENTER": "月见山宝可梦中心",
    "ROCK_TUNNEL_POKECENTER": "岩山隧道宝可梦中心",
    "VIRIDIAN_FOREST": "常青森林", "VIRIDIAN_FOREST_NORTH_GATE": "常青森林北门",
    "VIRIDIAN_FOREST_SOUTH_GATE": "常青森林南门",
    "INDIGO_PLATEAU_LOBBY": "宝可梦联盟大厅",
    "CERULEAN_TRASHED_HOUSE_COPY": "华蓝市 · 被破坏的民居（后门）",
    "CINNABAR_MART_COPY": "红莲友好商店（另一入口）",
}
PARTS = {
    "MART": "友好商店", "POKECENTER": "宝可梦中心", "GYM": "道馆",
    "TRADE_HOUSE": "交换民居", "SCHOOL_HOUSE": "宝可梦学校", "NICKNAME_HOUSE": "昵称民居",
    "NIDORAN_HOUSE": "尼多朗民居", "SPEECH_HOUSE": "民居", "TRASHED_HOUSE": "遭破坏的民居",
    "PIDGEY_HOUSE": "波波民居", "DINER": "餐馆", "CHIEF_HOUSE": "负责人家",
    "HOTEL": "旅馆", "CUBONE_HOUSE": "可拉可拉民居", "BILLS_GRANDPAS_HOUSE": "正辉爷爷家",
    "MEETING_ROOM": "会馆", "OLD_ROD_HOUSE": "破旧钓竿之家", "GOOD_ROD_HOUSE": "好钓竿之家",
    "BADGE_HOUSE": "徽章说明屋",
}
AREAS = {"EAST": "东区", "WEST": "西区", "NORTH": "北区", "CENTER": "中央区"}


def label(key):
    if key in TOWNS:
        return [key, TOWNS[key], "", ""]
    if re.fullmatch(r"ROUTE_\d+", key):
        return [key, key[6:] + " 号道路", "", ""]
    if key in SPECIAL:
        return [key, SPECIAL[key], "", ""]
    for prefix, name in GROUPS.items():
        if key.startswith(prefix + "_"):
            floor = key[len(prefix) + 1:]
            if floor in FLOORS or re.fullmatch(r"B?\d+F", floor):
                return [key, name, FLOORS.get(floor, floor), prefix]
    if key.startswith("SAFARI_ZONE_"):
        parts = key[12:].split("_REST_HOUSE")
        area = AREAS.get(parts[0], {"GATE": "入口", "SECRET_HOUSE": "秘密小屋"}.get(parts[0], parts[0]))
        return [key, "狩猎地带", area + ("休息室" if len(parts) > 1 else ""), "SAFARI_ZONE"]
    if key.startswith("CINNABAR_LAB"):
        room = {"": "大厅", "_TRADE_ROOM": "交换室", "_METRONOME_ROOM": "研究室",
                "_FOSSIL_ROOM": "化石复原室"}[key[12:]]
        return [key, "红莲研究所", room, "CINNABAR_LAB"]
    if match := re.fullmatch(r"(DIGLETTS_CAVE|UNDERGROUND_PATH)_ROUTE_(\d+)(_COPY)?", key):
        name = "地鼠洞穴" if match[1] == "DIGLETTS_CAVE" else "地下通道"
        return [key, f"{name} · {match[2]} 号道路入口" + ("（另一侧）" if match[3] else ""), "", ""]
    if match := re.fullmatch(r"ROUTE_(\d+)_(\w+)", key):
        kind = {"GATE": "关卡", "TRADE_HOUSE": "交换民居", "FLY_HOUSE": "飞翔民居",
                "SUPER_ROD_HOUSE": "厉害钓竿之家"}[match[2]]
        return [key, f"{match[1]} 号道路{kind}", "", ""]
    city, _, kind = key.partition("_")
    return [key, f"{CITY_PREFIXES[city]}{PARTS[kind]}", "", ""]


def main():
    source = Path(sys.argv[1]) / "constants" / "map_constants.asm"
    pattern = r"^\s*map_const\s+(\w+)\s*,\s*(\d+)\s*,\s*(\d+)\s*;\s*\$([0-9A-Fa-f]+)"
    rows = {}
    for key, width, _, id_ in re.findall(pattern, source.read_text(), re.M):
        if int(width):
            rows[int(id_, 16)] = label(key)
    target = Path(__file__).resolve().parents[1] / "editor" / "map_index.json"
    target.write_text("{\n" + ",\n".join(f'  "{i}": {json.dumps(row, ensure_ascii=False)}' for i, row in rows.items())
                      + "\n}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
