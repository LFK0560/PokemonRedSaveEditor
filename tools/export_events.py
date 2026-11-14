"""Export the event rows and their save conditions from the supported ROM."""
import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.events import CATEGORIES, EventIndex
from editor.maps import Atlas
from editor.rom import Catalog


def bit_list(bits):
    return "、".join(f"0x{offset:04X} & 0x{mask:02X}" for offset, mask in bits)


def export(rom: Path, destination: Path):
    index = EventIndex(Atlas(Catalog.load(rom)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("地图 ID", "地图", "对象 / 事件索引", "X", "Y", "类别", "名称", "复位支持",
                         "清除的 SRAM 位", "仅观察的 SRAM 位", "存档条件", "禁用原因", "证据"))
        for e in index.by_key.values():
            conditions = []
            if e.flags:
                state = "支持单独复位"
                conditions.append("主区校验有效且所列清除位均已设置")
            elif e.cooperative:
                state = "可重复互动"
            elif "待验证" in e.disabled:
                state = "复位规则待验证"
            else:
                state = "禁用"
            if e.idle_at is not None:
                conditions.append(f"地图脚本状态 0x{e.idle_at:04X} 为 0")
            if e.requires_clear:
                conditions.append(f"{bit_list(e.requires_clear)} 为 0")
            area = index.atlas.areas[e.map_id]
            writer.writerow((f"0x{area.id:02X}", area.title, e.id, e.x, e.y, CATEGORIES[e.kind],
                             e.name, state, bit_list(e.flags), bit_list(e.observed), "。".join(conditions),
                             e.disabled, e.evidence))
    print(f"Exported {len(index.by_key)} event rows to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.rom, args.destination)
