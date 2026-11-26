from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from PIL import Image, ImageDraw

from .rom import Catalog, rom_address, word
from .map_tables import MapTables, discover_maps


MAP_INFO = Path(__file__).with_name("map_index.json")
MAP_COUNT = 0xF8
OUTDOOR = 0x25
WORLD_SHADES = (239, 185, 115, 36)


@dataclass(frozen=True)
class Object:
    id: int
    x: int
    y: int
    sprite: int
    text: int
    script: int
    kind: str
    value: int
    level: int


@dataclass(frozen=True)
class Warp:
    x: int
    y: int
    map_id: int
    entrance: int


@dataclass(frozen=True)
class Area:
    id: int
    key: str
    name: str
    floor: str
    group: str
    bank: int
    header: int
    tileset: int
    w: int
    h: int
    blocks: int
    script: int
    links: tuple[tuple[str, int, int], ...]
    warps: tuple[Warp, ...]
    objects: tuple[Object, ...]

    @property
    def title(self) -> str:
        return f"{self.name} · {self.floor}" if self.floor else self.name


@dataclass(frozen=True)
class OverviewPoint:
    x: int
    y: int
    name: str
    ids: tuple[int, ...]


def signed(value: int) -> int:
    return value if value < 128 else value - 256


def unpack_tiles(data: bytes) -> Image.Image:
    pixels = bytearray()
    for i in range(0, len(data), 2):
        low, high = data[i:i + 2]
        pixels.extend(WORLD_SHADES[((high >> bit) & 1) * 2 + ((low >> bit) & 1)] for bit in range(7, -1, -1))
    return Image.frombytes("L", (8, len(data) // 2), bytes(pixels))


class Atlas:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.rom = catalog.rom
        index = json.loads(MAP_INFO.read_text(encoding="utf-8"))
        reference = json.loads(Path(__file__).with_name("reference.json").read_text(encoding="utf-8"))
        self.reference_areas = set()
        self.note = ""
        try:
            self.tables = MapTables(0xC23D, 0x1AE, 0xC7AC) if catalog.verified else discover_maps(self.rom)
        except (ValueError, IndexError) as exc:
            self.tables = None
            self.note = str(exc)
        self.areas = {}
        references = {v["id"]: v for v in reference["areas"]}
        for key, fields in index.items():
            id_ = int(key)
            if self.tables:
                try:
                    self.areas[id_] = self.read_area(id_, fields)
                    continue
                except (ValueError, IndexError):
                    pass
            values = references[id_].copy()
            values["links"] = tuple(tuple(v) for v in values["links"])
            values["warps"] = tuple(Warp(**v) for v in values["warps"])
            values["objects"] = tuple(Object(**v) for v in values["objects"])
            self.areas[id_] = Area(**values)
            self.reference_areas.add(id_)
        if self.tables and not catalog.verified:
            # Yellow and hacks may use map IDs outside the old reference list.
            for id_ in range(256):
                if id_ in self.areas:
                    continue
                try:
                    self.areas[id_] = self.read_area(id_, [f"MAP_{id_:02X}", f"地图 {id_:02X}", "", ""])
                except (ValueError, IndexError):
                    continue
        self.positions = self.world_positions()
        self.groups = {}
        for area in self.areas.values():
            if area.group:
                self.groups.setdefault(area.group, []).append(area.id)
        for ids in self.groups.values():
            ids.sort(key=lambda i: (not self.areas[i].floor.lstrip("B").rstrip("F").isdigit(),
                                   abs(self.floor_number(self.areas[i].floor)),
                                   self.areas[i].floor.startswith("B"), i))
        self.overview = (self.read_overview() if catalog.verified else
                         [OverviewPoint(v["x"], v["y"], v["name"], tuple(v["ids"])) for v in reference["overview"]])
        self.exit_links = self.read_exits()

    @staticmethod
    def floor_number(label: str) -> int:
        number = label.strip("BF")
        return int(number) if number.isdigit() else 99

    def read_area(self, id_: int, fields: list[str]) -> Area:
        r = self.rom
        bank = r[self.tables.banks + id_]
        header_pointer = word(r, self.tables.headers + id_ * 2)
        if not 0x4000 <= header_pointer < 0x8000:
            raise ValueError("地图头指针越界。")
        header = rom_address(bank, header_pointer)
        tileset, height, width = r[header:header + 3]
        if not (0 < bank < len(r)//0x4000 and tileset < 64 and 1 <= height <= 96 and 1 <= width <= 96):
            raise ValueError("地图尺寸或图块编号越界。")
        blocks = rom_address(bank, word(r, header + 3))
        texts = rom_address(bank, word(r, header + 5))
        script = rom_address(bank, word(r, header + 7))
        if blocks + width*height > len(r) or not (0 <= texts < len(r) and 0 <= script < len(r)):
            raise ValueError("地图资料指针越界。")
        pos = header + 10
        links = []
        for bit, direction, axis in [(8, "north", 8), (4, "south", 8), (2, "west", 7), (1, "east", 7)]:
            if r[header + 9] & bit:
                links.append((direction, r[pos], -signed(r[pos + axis]) // 2))
                pos += 11
        pos = rom_address(bank, word(r, pos)) + 1
        if r[pos] > 64:
            raise ValueError("地图出口数量异常。")
        warps = []
        for _ in range(r[pos]):
            pos += 1
            y, x, to, map_id = r[pos:pos + 4]
            warps.append(Warp(x, y, map_id, to))
            pos += 3
        pos += 1
        if r[pos] > 64:
            raise ValueError("地图告示牌数量异常。")
        pos += 1 + r[pos] * 3
        if r[pos] > 32:
            raise ValueError("地图对象数量异常。")
        objects = []
        for i in range(r[pos]):
            pos += 1
            sprite, y, x, _, _, flags = r[pos:pos + 6]
            text = flags & 0x3F
            pointer = word(r, texts + (text - 1) * 2)
            obj_script = rom_address(bank, pointer) if text and pointer < 0x8000 else -1
            kind, value, level = "npc", 0, 0
            if flags & 0x40:
                value, level = r[pos + 6:pos + 8]
                kind = "trainer" if value >= 200 else "fixed"
                pos += 2
            elif flags & 0x80:
                kind, value = "item", r[pos + 6]
                pos += 1
            objects.append(Object(i + 1, x - 4, y - 4, sprite, text, obj_script, kind, value, level))
            pos += 5
        return Area(id_, *fields, bank, header, tileset, width, height, blocks, script,
                    tuple(links), tuple(warps), tuple(objects))

    def world_positions(self) -> dict[int, tuple[int, int]]:
        positions = {0: (0, 0)}
        todo = deque([0])
        while todo:
            id_ = todo.popleft()
            a = self.areas[id_]
            x, y = positions[id_]
            for direction, target, shift in a.links:
                if target in positions or target not in self.areas or target >= OUTDOOR:
                    continue
                b = self.areas[target]
                directions = {"north": (x + shift, y - b.h), "south": (x + shift, y + a.h),
                              "west": (x - b.w, y + shift), "east": (x + a.w, y + shift)}
                positions[target] = directions[direction]
                todo.append(target)
        return {i: (x * 32, y * 32) for i, (x, y) in positions.items()}

    def read_exits(self) -> dict[int, set[int]]:
        result = {}
        for a in self.areas.values():
            if a.id >= OUTDOOR:
                continue
            for warp in a.warps:
                if warp.map_id in self.areas and warp.map_id >= OUTDOOR:
                    result.setdefault(warp.map_id, set()).add(a.id)
        return result

    def text(self, at: int, size: int = 22) -> str:
        return self.catalog.charset.decode(self.rom[at:at + size], rom_text=True)

    def read_overview(self) -> list[OverviewPoint]:
        points = {}
        offset = 0x71344
        for i in range(OUTDOOR):
            coord = self.rom[offset]
            if i in self.positions:
                points[coord] = OverviewPoint((coord & 15) * 8 + 20, (coord >> 4) * 8 + 12,
                                              self.areas[i].name, (i,))
            offset += 3
        current = OUTDOOR
        while self.rom[offset] != 255:
            end, coord = self.rom[offset:offset + 2]
            if coord not in points:
                ids = tuple(i for i in range(current, end) if i in self.areas)
                if ids:
                    name = self.text(rom_address(0x1C, word(self.rom, offset + 2)))
                    points[coord] = OverviewPoint((coord & 15) * 8 + 20, (coord >> 4) * 8 + 12, name, ids)
            current = end
            offset += 4
        return list(points.values())

    @lru_cache(maxsize=1)
    def town_map(self) -> Image.Image:
        if not self.catalog.verified:
            bitmap = Image.new("RGB", (160, 144), "#edf2e6")
            draw = ImageDraw.Draw(bitmap)
            points = {id_: (p.x, p.y) for p in self.overview for id_ in p.ids}
            for id_, area in self.areas.items():
                for _, target, _ in area.links:
                    if id_ in points and target in points:
                        draw.line((points[id_], points[target]), fill="#8baf9b", width=3)
            for point in self.overview:
                draw.rectangle((point.x-2, point.y-2, point.x+2, point.y+2), fill="#2b6453")
            return bitmap
        r = self.rom
        tiles = unpack_tiles(r[0x125A8:0x126A8])
        bitmap = Image.new("L", (160, 144), WORLD_SHADES[0])
        index = 0
        end = r.index(0, 0x7111F)
        for run in r[0x7111F:end]:
            tile = (run >> 4) * 8
            piece = tiles.crop((0, tile, 8, tile + 8))
            for _ in range(run & 15):
                bitmap.paste(piece, (index % 20 * 8, index // 20 * 8))
                index += 1
        return bitmap

    @lru_cache(maxsize=24)
    def tileset(self, id_: int) -> tuple[Image.Image, bytes]:
        at = self.tables.tilesets + id_ * 12
        bank = self.rom[at]
        blocks = rom_address(bank, word(self.rom, at + 1))
        tiles = rom_address(bank, word(self.rom, at + 3))
        return unpack_tiles(self.rom[tiles:tiles + 0x600]), self.rom[blocks:blocks + 0x800]

    @lru_cache(maxsize=48)
    def floor_image(self, id_: int) -> Image.Image:
        a = self.areas[id_]
        if id_ in self.reference_areas or not self.tables or self.tables.tilesets is None:
            return self.schematic(a)
        try:
            return self.render_floor(a)
        except (ValueError, IndexError, TypeError):
            return self.schematic(a)

    @staticmethod
    def schematic(a):
        bitmap = Image.new("RGB", (a.w*32, a.h*32), "#f0f3ed")
        draw = ImageDraw.Draw(bitmap)
        for x in range(0, bitmap.width, 16):
            draw.line((x, 0, x, bitmap.height), fill="#dae3d8")
        for y in range(0, bitmap.height, 16):
            draw.line((0, y, bitmap.width, y), fill="#dae3d8")
        return bitmap

    def render_floor(self, a):
        tiles, layout = self.tileset(a.tileset)
        grid = self.rom[a.blocks:a.blocks + a.w * a.h]
        bitmap = Image.new("L", (a.w * 32, a.h * 32), WORLD_SHADES[0])
        blocks = {}
        for block in set(grid):
            piece = Image.new("L", (32, 32))
            for i, tile in enumerate(layout[block * 16:(block + 1) * 16]):
                tile &= 127
                piece.paste(tiles.crop((0, tile * 8, 8, tile * 8 + 8)), (i % 4 * 8, i // 4 * 8))
            blocks[block] = piece
        for i, block in enumerate(grid):
            bitmap.paste(blocks[block], (i % a.w * 32, i // a.w * 32))
        return bitmap

    @lru_cache(maxsize=72)
    def sprite(self, id_: int) -> Image.Image:
        if not self.catalog.verified:
            return Image.new("RGBA", (16, 16))
        table = 0x17B27 + (id_ - 1) * 4
        start = rom_address(self.rom[table + 3], word(self.rom, table))
        tiles = unpack_tiles(self.rom[start:start + 64])
        bitmap = Image.new("RGBA", (16, 16))
        for tile in range(4):
            part = tiles.crop((0, tile * 8, 8, tile * 8 + 8))
            part = Image.merge("RGBA", (part, part, part, part.point(lambda x: 0 if x == WORLD_SHADES[0] else 255)))
            bitmap.paste(part, (tile % 2 * 8, tile // 2 * 8))
        return bitmap
