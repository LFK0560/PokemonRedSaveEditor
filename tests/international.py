"""Check international ROM table discovery and the shared SRAM editor."""
import argparse
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.charset import SingleByteCharset
from editor.files import Document
from editor.rom import Catalog
from editor.save import (
    ACTIVE_BOX, BAG, BOX_NUMBER, CURRENT_MAP, MAIN_SUM, PARTY, PC_ITEMS,
    PLAYER, Entry, Save, checksum,
)


def new_game(catalog):
    from emulator import Game

    game = Game(catalog)
    game.title(False)
    encode = lambda s: b"".join(catalog.charset.encoding[c] for c in s)
    name_menus = 0
    for i in range(100):
        game.press("a", 140, 5)
        tiles = bytes(game.mem[0xC3A0:0xC3A0 + 360])
        if encode("NEW NAME") in tiles:
            game.press("down", 35, 4)
            game.press("a", 140, 5)
            name_menus += 1
        if name_menus == 2 and i > 70:
            game.press("start", 40, 5)
            if encode("SAVE") in bytes(game.mem[0xC3A0:0xC3A0 + 360]):
                for _ in range(3):
                    game.press("down", 30, 4)
                for _ in range(5):
                    game.press("a", 190, 5)
                raw = game.close(flush=True)
                assert Save(catalog, raw).count(None) == 0
                return raw
    game.close()
    raise AssertionError("Did not reach the in-game Save menu")


def fixture(catalog):
    data = bytearray(0x8000)
    data[PLAYER:PLAYER + 11] = catalog.charset.nickname("TEST")
    data[CURRENT_MAP] = 0x26
    for offset in (PARTY, ACTIVE_BOX, BAG[0], PC_ITEMS[0]):
        data[offset + 1] = 255
    data[MAIN_SUM] = checksum(data, PLAYER, MAIN_SUM)
    return bytes(data)


def check_game(catalog, raw):
    from emulator import Game

    shift = 1 if "YELLOW" in catalog.version else 0
    game = Game(catalog, raw)
    status_address = 0xD088 - shift
    for _ in range(16):
        game.press("start", 38, 4)
        if game.mem[status_address] == 2:
            break
    assert game.mem[status_address] == 2
    for _ in range(4):
        game.press("a", 100)
    assert (game.mem[0xD163 - shift], game.mem[0xD16B - shift]) == (1, 0x99)
    assert tuple(game.mem[0xD31D - shift:0xD321 - shift]) == (1, 0x14, 99, 255)
    assert tuple(game.mem[0xD53A - shift:0xD53E - shift]) == (1, 0x04, 1, 255)
    assert game.mem[0xDA80 - shift] == 1
    game.close()


def check(path, emulator=False):
    catalog = Catalog.load(path)
    assert not catalog.verified
    assert [s.dex for s in catalog.by_dex] == list(range(1, 152))
    assert len(catalog.moves) == 166 and len(catalog.items) == 138
    assert catalog.base_pp[1] == 35 and catalog.species[0x99].base == (45, 49, 49, 45, 65)
    assert catalog.tables.machines != 0x1391B
    assert catalog.moves[1] in ("POUND", "ECRAS'FACE", "PFUND", "DESTRUCTOR", "LIBBRA")
    use_game = emulator and "英文" in catalog.version
    source = new_game(catalog) if use_game else fixture(catalog)
    with TemporaryDirectory(prefix="international-save-") as folder:
        path = Path(folder) / "test.sav"
        path.write_bytes(source)
        doc = Document.load(path, catalog)
        assert doc.import_backup.read_bytes() == source
        assert doc.save() is None and path.read_bytes() == source
        model = doc.model
        mon = model.new_mon(0x99, 12)
        model.apply_mon(None, None, replace(mon, nickname="BETA12", status=64))
        model.apply_mon(model.current_box, None, model.new_mon(0xB0, 8))
        model.apply_mon(1, None, model.new_mon(0xB1, 9))
        model.apply_mon(11, None, model.new_mon(0x54, 10))
        model.apply_items(False, None, Entry(0x14, 99))
        model.apply_items(True, 0 if model.items(True) else None, Entry(0x04, 1))
        expected = bytes(model.data)
        allowed = (set(range(PARTY, PARTY + 404)) | set(range(ACTIVE_BOX, ACTIVE_BOX + 1122))
                   | set(range(BAG[0], BAG[0] + 42)) | set(range(PC_ITEMS[0], PC_ITEMS[0] + 102))
                   | set(range(0x4000, 0x5A53)) | set(range(0x6000, 0x7A53)) | {MAIN_SUM, BOX_NUMBER})
        assert {i for i, (a, b) in enumerate(zip(source, expected)) if a != b} <= allowed
        previous = doc.save()
        assert previous.read_bytes() == source and path.read_bytes() == expected
        restored = Save(catalog, expected)
        assert restored.read_mon(None, 0).nickname == "BETA12"
        assert restored.count(0) == restored.count(1) == restored.count(11) == 1
        assert expected[0x271C:0x2745] == source[0x271C:0x2745]
        second = Document.load(path, catalog)
        assert second.import_backup.name == "test_2.sav"
        if use_game:
            check_game(catalog, expected)
    print(f"PASS {catalog.version} — tables, SRAM edits, backups" + (", game Save and Continue" if use_game else ""))


def check_gui(roms):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from editor.forms import MonDialog
    from editor.window import MainWindow

    app = QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    with TemporaryDirectory(prefix="international-ui-") as folder:
        for i, path in enumerate(roms):
            assert window.load_rom(path)
            file = Path(folder) / f"locale{i}.sav"
            file.write_bytes(fixture(window.catalog))
            assert window.load_save(file)
            assert "兼容测试" in window.rom_label.text()
            assert window.map_slot.currentWidget() is window.map_empty
            dialog = MonDialog(window, window.document.model, None, None)
            dialog.show()
            app.processEvents()
            QTest.mouseClick(dialog.accept_button, Qt.MouseButton.LeftButton)
            assert not dialog.isVisible() and window.document.model.count(None) == 1
            window.applied("添加兼容测试精灵")
            assert window.save_file()
            assert Save(window.catalog, file.read_bytes()).count(None) == 1
            dialog.deleteLater()
        window.close()
    print("PASS international Qt imports, core editor, saves and ROM switching")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path, nargs="+")
    parser.add_argument("--emulator", action="store_true")
    parser.add_argument("--gui", action="store_true")
    args = parser.parse_args()
    for language, text in (("en", "BETA12"), ("fr", "éàç"), ("de", "ÄÖÜß"), ("es", "Ññ¿¡"), ("it", "CITTÀ")):
        codec = SingleByteCharset(language)
        assert codec.decode(codec.nickname(text)) == text
    for rom in args.rom:
        check(rom, args.emulator)
    if args.gui:
        check_gui(args.rom)
