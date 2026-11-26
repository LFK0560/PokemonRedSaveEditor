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
        writer.writerow(("地图 ID", "地图", "对象 / 事件索引", "X", "Y", "类别", "名称", "认证",
                         "编辑方式", "清除的国际版参考位", "影响说明", "证据"))
        for e in index.by_key.values():
            if e.flags:
                state = "开放复位"
            else:
                state = "自定义关联 / 直接编辑标记"
            area = index.atlas.areas[e.map_id]
            writer.writerow((f"0x{area.id:02X}", area.title, e.id, e.x, e.y, CATEGORIES[e.kind],
                             e.name, "已认证规则" if e.certified else "未认证", state, bit_list(e.flags),
                             e.disabled, e.evidence))
    print(f"Exported {len(index.by_key)} event rows to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.rom, args.destination)
