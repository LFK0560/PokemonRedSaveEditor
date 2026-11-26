"""Read table operands from the Gen I map-loading routines."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MapTables:
    banks: int
    headers: int
    tilesets: int | None


def address(bank, pointer):
    if not 0 <= pointer < 0x8000:
        raise ValueError("地图指针越界。")
    return pointer if pointer < 0x4000 else (bank-1)*0x4000+pointer


def discover_maps(rom):
    # LoadMapHeader indexes the ROM0 pointer table with twice the map ID.
    headers = [int.from_bytes(m[1], "little") for m in re.finditer(
        rb"\x21(..)\xfa..\xcb\x27\x30.\x24\x85\x6f\x30.\x24\x2a\x66\x6f", rom[:0x4000], re.S)]
    # SwitchToMapRomBank reads a separate bank table.
    banks = [address(m[1][0], int.from_bytes(m[2], "little")) for m in re.finditer(
        rb"\xe5\xc5\x4f\x06\x00\x3e(.)\xcd..\x21(..)\x09\x7e", rom[:0x4000], re.S)]
    chosen = None
    for h in headers:
        for b in banks:
            try:
                for map_id in (0, 1, 2, 3, 4, 12, 36):
                    at = address(rom[b+map_id], int.from_bytes(rom[h+map_id*2:h+map_id*2+2], "little"))
                    if not (rom[at] < 64 and 1 <= rom[at+1] <= 96 and 1 <= rom[at+2] <= 96):
                        raise ValueError("地图头形状不符。")
                chosen = (b, h)
                break
            except (ValueError, IndexError):
                continue
        if chosen:
            break
    if not chosen:
        raise ValueError("未定位地图表，使用未认证参考定位图。")
    tilesets = None
    for m in re.finditer(rb"\xff\xff\xff\x52", rom):
        at = m.start()-7
        if at < 0:
            continue
        try:
            for i in range(24):
                p = at+i*12
                bank = rom[p]
                if not 0 < bank < len(rom)//0x4000:
                    raise ValueError("图块银行无效。")
                for q in (p+1, p+3):
                    pointer = int.from_bytes(rom[q:q+2], "little")
                    if not 0x4000 <= pointer < 0x8000:
                        raise ValueError("图块指针无效。")
            tilesets = at
            break
        except (ValueError, IndexError):
            continue
    return MapTables(*chosen, tilesets)
