"""Game Boy emulator regression against the supplied ROM and temporary SRAM copies."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import sys

from pyboy import PyBoy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.events import EventIndex
from editor.maps import Atlas
from editor.rom import Catalog, save_address
from editor.save import MAIN_SUM, PLAYER, Entry, Save, checksum


class Game:
    def __init__(self, catalog, sram=None):
        self.boy = PyBoy(BytesIO(catalog.rom), ram_file=BytesIO(sram) if sram else None,
                         window="null", sound_emulated=False, log_level="ERROR")
        self.boy.set_emulation_speed(0)
        self.boy.tick(280, render=False)

    @property
    def mem(self):
        return self.boy.memory

    def press(self, key, frames=40, hold=5):
        self.boy.button(key, hold)
        self.boy.tick(frames, render=True)

    def title(self, continuing):
        if not continuing:
            for _ in range(10):
                self.press("start", 38, 4)
        else:
            for _ in range(16):
                self.press("start", 38, 4)
                if self.mem[0xD088] == 2:
                    return
            raise AssertionError("Continue menu did not detect the cartridge save")

    def resume(self, *, reload_map=False):
        self.title(True)
        if reload_map:
            # Continue normally reuses the map header copied from SRAM. For a
            # fixture that starts on another map, let the ROM load the complete
            # corresponding header, objects and warp fields during entry.
            self.mem[0xD367] &= 0x7F
        for _ in range(4):
            self.press("a", 100)
        assert self.mem[0xD088] == 2

    def location(self):
        return self.mem[0xD35E], self.mem[0xD362], self.mem[0xD361]

    def route(self, steps):
        for key, count in steps:
            for _ in range(count):
                self.press(key, 30, 7)

    def capture(self, folder, name):
        self.boy.screen.image.resize((640, 576), 0).save(folder / f"{name}.png")

    def close(self, flush=False):
        out = BytesIO()
        self.boy.stop(save=flush, ram_file=out if flush else None)
        return out.getvalue()


def fresh_game(catalog, atlas, folder):
    game = Game(catalog)
    game.title(False)
    for _ in range(9):
        game.press("a", 180, 7)
    sequence = ["b", "a"] + ["down"] * 4 + ["a", "up", "up", "left"]
    for key in sequence:
        game.press(key, 42, 7 if key == "a" else 4)
    for _ in range(3):
        game.press("a", 145, 7)
    for followup in (5, 6):
        game.press("down", 32, 4)
        game.press("a", 180, 7)
        for _ in range(followup):
            game.press("a", 165, 7)
    assert game.location() == (0x26, 3, 6)
    game.press("start", 42, 4)
    for _ in range(3):
        game.press("down", 30, 4)
    game.press("a", 50, 7)
    game.press("a", 160, 7)
    game.press("a", 160, 7)
    game.press("a", 260, 7)
    assert game.mem[0xD088] == 2
    game.capture(folder, "01_新开档")
    raw = game.close(flush=True)
    model = Save(catalog, raw, atlas.areas)
    assert not model.initialized and model.count(None) == 0
    (folder / "新开档[赤红].srm").write_bytes(raw)
    print(f"PASS fresh game via title and in-game Save. Player={model.player}.")
    return raw


def zapdos(catalog, atlas, index, before, after, folder):
    model = Save(catalog, before, atlas.areas)
    target = index.by_key[0x53, "9"]
    assert target.reset(model) and not target.reset(model)
    assert model.data == after
    for name, raw in (("before", before), ("reset", model.data)):
        game = Game(catalog, raw)
        game.resume()
        assert game.location() == (0x53, 4, 4)
        game.route([("down", 4)])
        assert game.location() == (0x53, 4, 8)
        game.capture(folder, "02_闪电鸟_" + name)
        for _ in range(5):
            game.press("a", 120)
        if name == "reset":
            assert (game.mem[0xD057], game.mem[0xCFE5], game.mem[0xCFF3]) == (1, 0x4B, 50)
            game.capture(folder, "03_闪电鸟_战斗")
        else:
            assert game.mem[0xD057] == 0
        game.close()
    print("PASS Continue and face Zapdos at (4,9). Control absent, reset starts battle 4B Lv50.")


def warp_fixture(raw, atlas, map_id, x, y, last_map):
    # Set a QA-only starting position. The game loads its own map data and
    # sprites during Continue. This routine is never called by the editor.
    ar = atlas.areas[map_id]
    data = bytearray(raw)
    base = save_address(0xD35E)
    pointer = 0xC6E8 + 7 + ar.w + (ar.w + 6) * (y // 2) + x // 2
    data[base:base + 8] = bytes((map_id, *pointer.to_bytes(2, "little"), y, x, y % 2, x % 2, last_map))
    data[save_address(0xD367):save_address(0xD371)] = atlas.rom[ar.header:ar.header + 10]
    data[save_address(0xD72E)] &= ~0x20
    data[MAIN_SUM] = checksum(data, PLAYER, MAIN_SUM)
    return bytes(data)


def other_fixed_battles(catalog, atlas, index, before, folder):
    for map_id, object_id, last_map, species, level in (
            (0xA2, "3", 0x1F, 0x4A, 50), (0xE3, "1", 0x15, 0x83, 70)):
        event = index.by_key[map_id, object_id]
        raw = bytearray(warp_fixture(before, atlas, map_id, event.x, event.y + 1, last_map))
        for offset, mask in event.flags:
            raw[offset] |= mask
        raw[event.idle_at] = 0
        raw[MAIN_SUM] = checksum(raw, PLAYER, MAIN_SUM)
        model = Save(catalog, raw, atlas.areas)
        assert event.reset(model)
        for changed, data in ((False, raw), (True, model.data)):
            game = Game(catalog, data)
            game.resume(reload_map=True)
            assert game.location() == (map_id, event.x, event.y + 1)
            game.press("up", 30, 4)
            for _ in range(8):
                game.press("a", 85)
                if game.mem[0xD057]:
                    break
            if changed:
                assert (game.mem[0xD057], game.mem[0xCFE5], game.mem[0xCFF3]) == (1, species, level)
                game.capture(folder, f"10_固定对战_{map_id:02X}")
            else:
                assert not (game.mem[0xD057] and game.mem[0xCFE5] == species and game.mem[0xCFF3] == level)
            game.close()
        print(f"PASS {event.name} reappears and starts its original battle after Continue.")


def trainer(catalog, atlas, index, before, folder):
    event = index.by_key[0x16, "2"]
    model = Save(catalog, warp_fixture(before, atlas, 0x16, 26, 10, 0x16), atlas.areas)
    assert event.status(model) == "已完成"
    for changed in (False, True):
        if changed:
            assert event.reset(model)
        g = Game(catalog, model.data)
        g.resume(reload_map=True)
        assert g.location() == (0x16, 26, 10)
        g.press("up", 30, 4)
        for _ in range(8):
            g.press("a", 100)
        if changed:
            assert g.mem[0xD057] == 2, (g.location(), g.mem[0xD057])
            g.capture(folder, "04_普通训练家_重战")
            exp = int.from_bytes(g.mem[0xD179:0xD17C], "big")
            money = int.from_bytes(g.mem[0xD347:0xD34A], "big")
            for i in range(64):
                # Decline the optional switch after the first knockout.
                g.press("b" if 15 <= i <= 22 and i % 2 == 0 else "a", 80)
                if not g.mem[0xD057]:
                    break
            offset, mask = event.flags[0]
            assert g.mem[0xD057] == 0 and g.mem[offset - save_address(0)] & mask
            assert int.from_bytes(g.mem[0xD179:0xD17C], "big") > exp
            assert int.from_bytes(g.mem[0xD347:0xD34A], "big") > money
            g.capture(folder, "04_普通训练家_结算")
        else:
            assert g.mem[0xD057] == 0
        g.close()
    print("PASS Route 11 object 2 re-enters a trainer battle, grants EXP and money, and sets its completion bit.")


def item(catalog, atlas, index, before, folder, hidden=False):
    event = index.by_key[0x53, "H24" if hidden else "10"]
    raw = bytearray(warp_fixture(before, atlas, 0x53, event.x, event.y + 1, 0x15))
    if hidden:
        offset, mask = event.flags[0]
        raw[offset] |= mask
        raw[MAIN_SUM] = checksum(raw, PLAYER, MAIN_SUM)
    model = Save(catalog, raw, atlas.areas)
    original_lists = [model.items(pc) for pc in (False, True)]
    assert event.status(model) == "已完成" and event.reset(model)
    assert [model.items(pc) for pc in (False, True)] == original_lists
    assert {i for i in range(len(raw)) if raw[i] != model.data[i]} == {event.flags[0][0], MAIN_SUM}
    item_id = 0x4F if hidden else 0x26
    g = Game(catalog, model.data)
    g.resume(reload_map=True)
    assert g.location() == (0x53, event.x, event.y + 1)
    g.press("up", 30, 4)
    assert g.location() == (0x53, event.x, event.y + 1)
    g.press("a", 100)
    count = g.mem[0xD31D]
    live = [Entry(g.mem[0xD31E + i * 2], g.mem[0xD31F + i * 2]) for i in range(count)]
    total = lambda entries: sum(e.qty for e in entries if e.id == item_id)
    assert total(live) == total(original_lists[0]) + 1, (event.name, live, g.location())
    g.capture(folder, "06_隐藏道具" if hidden else "05_原位拾取")
    g.close()
    print(f"PASS {event.name} reappears at ({event.x},{event.y}); both item lists equal before pickup.")


def change_box(catalog, atlas, raw, folder):
    model = Save(catalog, raw, atlas.areas)
    pikachu = catalog.by_dex[24].id
    a = model.new_mon(pikachu, 12)
    # Exercise both initialized and never-switched box layouts through the
    # game. Red move and Chinese nickname originated in the same editor API.
    a = replace(a, nickname="测试皮卡丘", moves=(0x39, 0x54, 0x2D, 0),
                pp=(4, 30, 6, 0), pp_ups=(3, 0, 1, 0), status=64)
    model.apply_mon(None, None, a)
    model.apply_mon(0, None, model.new_mon(catalog.by_dex[3].id, 5))
    model.apply_mon(1, None, model.new_mon(catalog.by_dex[6].id, 7))
    model.apply_items(False, None, Entry(0x14, 99))
    model.apply_items(True, 0, Entry(0x04, 1))
    (folder / "开局编辑[三个位置].srm").write_bytes(model.data)
    # Run the actual Pokémon Center PC Change Box implementation on a
    # copy. Center coordinates are used only for this emulator fixture.
    fixture = warp_fixture(model.data, atlas, 0x29, 13, 4, 1)
    g = Game(catalog, fixture)
    g.resume(reload_map=True)
    assert (g.mem[0xD163], g.mem[0xDA80], g.mem[0xD5A0]) == (1, 1, 0x80)
    assert tuple(g.mem[0xD31D:0xD31D+4]) == (1, 0x14, 99, 255)
    assert tuple(g.mem[0xD53A:0xD53A+4]) == (1, 4, 1, 255)
    assert g.mem[0xD16B] == pikachu
    g.capture(folder, "07_PC场景")
    g.press("up", 145)
    for _ in range(5):
        g.press("a", 145)
    for _ in range(3):
        g.press("down", 145)
    g.capture(folder, "08_PC更换箱子")
    for _ in range(3):
        g.press("a", 145)
    g.press("down", 145)
    g.press("a", 145)
    assert (g.mem[0xD5A0], g.mem[0xDA80], g.mem[0xDA81]) == (0x81, 1, catalog.by_dex[6].id)
    g.capture(folder, "09_PC箱子2")
    disk = g.close(flush=True)
    result = Save(catalog, disk, atlas.areas)
    assert result.current_box == 1
    assert result.read_mon(0, 0).species == catalog.by_dex[3].id
    assert result.read_mon(1, 0).species == catalog.by_dex[6].id
    assert result.read_mon(None, 0).nickname == a.nickname
    assert result.read_mon(None, 0).moves == a.moves
    assert result.items(False) == [Entry(0x14, 99)]
    assert result.items(True) == [Entry(4, 1)]
    repeat = Game(catalog, disk)
    repeat.resume()
    assert (repeat.mem[0xD5A0], repeat.mem[0xDA80], repeat.mem[0xDA81]) == (0x81, 1, catalog.by_dex[6].id)
    repeat.close()
    print("PASS game loads edited party, bag and PC item lists, changes box and saves both boxes. Reboot verified.")


def main():
    rom, pre, post, output = map(Path, sys.argv[1:5])
    output.mkdir(parents=True, exist_ok=True)
    c = Catalog.load(rom)
    a = Atlas(c)
    index = EventIndex(a)
    fresh = fresh_game(c, a, output)
    before, after = pre.read_bytes(), post.read_bytes()
    zapdos(c, a, index, before, after, output)
    other_fixed_battles(c, a, index, before, output)
    trainer(c, a, index, before, output)
    item(c, a, index, before, output)
    item(c, a, index, before, output, hidden=True)
    change_box(c, a, fresh, output)


if __name__ == "__main__":
    main()
