"""Rebuild factual reference metadata from the original reference ROMs."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.events import EventIndex
from editor.maps import Atlas
from editor.rom import Catalog


def export(chinese, english, destination):
    catalog, names = Catalog.load(chinese), Catalog.load(english)
    if not catalog.verified:
        raise ValueError("重建参考资料需使用原已认证的中文参考 ROM。此工具不影响编辑器的开放策略。")
    atlas = Atlas(catalog)
    index = EventIndex(atlas)
    data = {
        "species": [dict(asdict(s), types=list(s.types), raw_name=list(s.raw_name),
                         machines=sorted(s.machines), default_name=names.default_nickname(s.id))
                    for s in catalog.by_dex],
        "moves": catalog.moves, "base_pp": catalog.base_pp,
        "items": [asdict(v) for v in catalog.items.values()],
        "growth": catalog.growth_coefficients,
        "areas": [asdict(v) for v in atlas.areas.values()],
        "positions": atlas.positions, "overview": [asdict(v) for v in atlas.overview],
        "events": [asdict(v) for v in index.by_key.values()],
        "source_rom_sha256": catalog.sha256,
    }
    destination.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote factual reference metadata to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chinese", type=Path)
    parser.add_argument("english", type=Path)
    parser.add_argument("destination", type=Path, nargs="?", default=Path("editor/reference.json"))
    args = parser.parse_args()
    export(args.chinese, args.english, args.destination)
