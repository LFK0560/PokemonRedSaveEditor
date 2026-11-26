"""Run format, event and Windows file regressions on temporary save copies."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.events import EventIndex
from editor.files import ChangedOnDisk, Document, snapshot
from editor.maps import Atlas
from editor.rom import Catalog
from editor.save import (
    ACTIVE_BOX, BAG, BOX_BANKS, BOX_SIZE, MAIN_SUM, PARTY, PLAYER, PC_ITEMS,
    Entry, InvalidSave, Save, checksum,
)


def expect_error(kind, match, function, *args):
    try:
        function(*args)
    except kind as exc:
        assert match in str(exc), str(exc)
    else:
        raise AssertionError(f"Expected {kind.__name__}: {match}")


def differences(before, after):
    return {i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b}


def format_checks(catalog, atlas, before, after, fresh):
    expect_error(ValueError, "ROM", Catalog, b"\0" * 0x200000)
    for raw in (before, after, fresh):
        Save(catalog, raw, atlas.areas)
    expect_error(InvalidSave, "32,768", Save, catalog, after[:-1])
    raw = bytearray(after)
    raw[MAIN_SUM] ^= 1
    expect_error(InvalidSave, "主区校验", Save, catalog, raw)
    raw = bytearray(after)
    raw[PARTY + 7] = 0
    raw[MAIN_SUM] = checksum(raw, PLAYER, MAIN_SUM)
    expect_error(InvalidSave, "结束标记", Save, catalog, raw)
    bank_end = BOX_BANKS[0] + 6 * BOX_SIZE
    raw = bytearray(after)
    raw[bank_end] ^= 1
    expect_error(InvalidSave, "合计校验", Save, catalog, raw)
    raw = bytearray(after)
    raw[bank_end + 1] ^= 1
    expect_error(InvalidSave, "独立校验", Save, catalog, raw)
    for species in catalog.species:
        for level in range(1, 101):
            assert catalog.level(species, catalog.experience(species, level)) == level
    assert set(catalog.minimum_levels) <= set(catalog.species)
    assert catalog.species_rule(0x99, 4)[0] == "unusual"
    assert catalog.species_rule(0x7C, 4)[0] == "normal"  # Metapod wild below evolution level
    assert catalog.minimum_levels[0x85] == 5  # Old Rod Magikarp
    assert catalog.move_rule(0x55, 30, 0x39)[0] == "unknown"  # Raichu with Surf
    assert len(catalog.charset.chinese) >= 6763
    expect_error(ValueError, "10 字节", catalog.charset.nickname, "一二三四五六")
    expect_error(ValueError, "ROM 字库", catalog.charset.nickname, "测试🦆")
    for text in ("测试妙蛙种", "PIKA25", "赤红"):
        assert catalog.charset.decode(catalog.charset.nickname(text)) == text
    untouched = Save(catalog, after, atlas.areas)
    expect_error(InvalidSave, "目标已满", untouched.apply_mon, None, None, untouched.new_mon(0x99))
    base = untouched.read_mon(None, 0)
    expect_error(InvalidSave, "挣扎", untouched.apply_mon, None, 0, replace(base, moves=(165, *base.moves[1:])))
    expect_error(InvalidSave, "PP", untouched.apply_mon, None, 0, replace(base, pp=(63, *base.pp[1:])))
    expect_error(InvalidSave, "当前 HP", untouched.apply_mon, None, 0, replace(base, hp=900))
    expect_error(InvalidSave, "防御", untouched.apply_mon, None, 0, replace(base, stats=(*base.stats[:2], 512, *base.stats[3:])))
    assert bytes(untouched.data) == after
    model = Save(catalog, fresh, atlas.areas)
    assert not model.initialized and not model.count(None)
    original = model.new_mon(0x99)
    expect_error(InvalidSave, "HP 溢出", model.apply_mon, None, None, replace(
        original, stats=(200, *original.stats[1:])))
    expect_error(InvalidSave, "公式上限", model.apply_mon, None, None, replace(
        original, hp=20, stats=(21, *original.stats[1:])))
    model.apply_mon(None, None, original)
    party = bytes(model.data)
    assert differences(fresh, party) <= set(range(PARTY, ACTIVE_BOX)) | {MAIN_SUM}
    model.apply_mon(model.current_box, None, model.new_mon(0xB0))
    local_box = bytes(model.data)
    assert differences(party, local_box) <= set(range(ACTIVE_BOX, ACTIVE_BOX + BOX_SIZE)) | {MAIN_SUM}
    other = (model.current_box + 1) % 12
    model.apply_mon(other, None, model.new_mon(0xB1))
    assert model.initialized and model.count(other) == model.count(model.current_box) == 1
    assert model.read_mon(other, 0).species == 0xB1
    assert model.count((other + 1) % 12) == 0
    for pc, (start, capacity) in ((False, BAG), (True, PC_ITEMS)):
        previous = bytes(model.data)
        expect_error(InvalidSave, "1–99", model.apply_items, pc, None, Entry(0x14, 0))
        expect_error(InvalidSave, "1–99", model.apply_items, pc, None, Entry(0x14, 100))
        expect_error(InvalidSave, "绕过", model.apply_items, pc, None, Entry(0x07, 1))
        expect_error(InvalidSave, "仅保留一份", model.apply_items, pc, None, Entry(0xC4, 2))
        assert previous == model.data
        model.apply_items(pc, None, Entry(0x14, 99))
        model.apply_items(pc, None, Entry(0x3B, 1))
        assert model.item_rule(pc, [], 0x3B, 1)[0] == "unusual"
        i = len(model.items(pc)) - 2
        model.apply_items(pc, i, Entry(0x04, 1))
        model.apply_items(pc, i + 1, None)
        assert model.items(pc)[i] == Entry(0x04, 1)
        assert differences(previous, model.data) <= set(range(start, start + 2 * capacity + 2)) | {MAIN_SUM}
        assert model.data[start + 1 + 2 * len(model.items(pc))] == 255
        while len(model.items(pc)) < capacity:
            model.apply_items(pc, None, Entry(0x14, 1))
        expect_error(InvalidSave, "目标已满", model.apply_items, pc, None, Entry(0x14, 1))
    print("PASS format, checksums, nicknames, 151 growth curves, stats and capacity, and edit boundaries")


def event_checks(catalog, atlas, before, after):
    for id_, area in atlas.areas.items():
        assert atlas.floor_image(id_).size == (area.w * 32, area.h * 32)
    assert len(atlas.areas) == 226 and len(atlas.positions) == 36 and len(atlas.overview) == 60
    index = EventIndex(atlas)
    enabled = [e for e in index.by_key.values() if e.flags]
    assert len(index.by_key) == 978 and len(enabled) == 416
    unique = set()
    for event in enabled:
        assert event.evidence and not event.disabled and unique.isdisjoint(event.flags)
        unique.update(event.flags)
        raw = bytearray(before)
        for offset, mask in event.requires_clear:
            raw[offset] &= ~mask
        if event.idle_at is not None:
            raw[event.idle_at] = 0
        for offset, mask in event.flags:
            raw[offset] |= mask
        raw[MAIN_SUM] = checksum(raw, PLAYER, MAIN_SUM)
        model = Save(catalog, raw, atlas.areas)
        assert event.status(model) == "已完成"
        assert event.reset(model)
        for offset, mask in event.flags:
            assert model.data[offset] == raw[offset] & ~mask
        assert differences(raw, model.data) <= {offset for offset, _ in event.flags} | {MAIN_SUM}
        assert not event.reset(model)
    zapdos = index.by_key[0x53, "9"]
    sample = Save(catalog, before, atlas.areas)
    assert zapdos.reset(sample)
    assert sample.data == after
    assert differences(before, after) == {0x285C, 0x2A80, MAIN_SUM}
    assert [(before[i], after[i]) for i in (0x285C, 0x2A80, MAIN_SUM)] == [
        (0x7E, 0x5E), (0x03, 0x01), (0xD9, 0xFB),
    ]
    assert not zapdos.reset(sample) and sample.data == after
    sample.data[0x285C] |= 0x20
    assert zapdos.status(sample) == "旗标状态不一致" and not zapdos.can_reset(sample)
    leader = index.by_key[0x36, "1"]
    assert leader.kind == "leader" and "徽章" in leader.disabled
    expect_error(InvalidSave, "徽章", leader.reset, sample)
    lift_guard = index.by_key[0xCA, "4"]
    expect_error(InvalidSave, "钥匙", lift_guard.reset, sample)
    one, two = index.by_key[0xD7, "H28"], index.by_key[0xD8, "H15"]
    assert (one.x, one.y) == (two.x, two.y) and one.flags != two.flags
    print(f"PASS all 226 map images, {len(enabled)} isolated event writes, floor identity and the exact Zapdos regression")


def file_checks(catalog, atlas, before, after):
    with TemporaryDirectory(prefix="口袋妖怪红_验收_") as temporary:
        root = Path(temporary)
        path = root / "发电厂[样本].srm"
        path.write_bytes(before)
        expected = snapshot(path)
        target = root / "备份" / date.today().isoformat()
        with ThreadPoolExecutor(max_workers=6) as executor:
            docs = list(executor.map(lambda _: Document.load(path, catalog, atlas.areas), range(6)))
        backups = {d.import_backup for d in docs}
        assert backups == {target / ("发电厂[样本]" + (f"_{n}" if n > 1 else "") + ".srm")
                           for n in range(1, 7)}
        assert all(p.read_bytes() == before for p in backups)
        doc = docs[0]
        assert doc.save() is None and snapshot(path) == expected
        copy = root / "无修改另存.srm"
        assert doc.save(copy) is None and copy.read_bytes() == before
        doc = Document.load(path, catalog, atlas.areas)
        assert doc.import_backup == target / "发电厂[样本]_7.srm"
        EventIndex(atlas).by_key[0x53, "9"].reset(doc.model)
        with patch("editor.files.replace_guarded", side_effect=OSError("模拟系统拒绝替换")):
            expect_error(OSError, "拒绝替换", doc.save)
        assert snapshot(path) == expected and doc.model.dirty
        assert not list(root.rglob(".pkred-*.tmp"))
        if sys.platform == "win32":
            with path.open("r+b"):
                expect_error(OSError, "", doc.save)
            assert snapshot(path) == expected and doc.model.dirty
        prior = doc.save()
        assert prior == target / "发电厂[样本]_覆盖前_2.srm"
        assert not doc.model.dirty and path.read_bytes() == after and prior.read_bytes() == before
        other = docs[1]
        expect_error(ChangedOnDisk, "打开后已更新", other.save)
        restore = root / "还原备份.srm"
        saved_copy = Document.load(prior, catalog, atlas.areas)
        saved_copy.save(restore)
        assert restore.read_bytes() == before
        assert path.read_bytes() == after
        unopened = root / "覆盖目标.srm"
        unopened.write_bytes(before)
        guard = snapshot(unopened)
        unopened.write_bytes(after)
        expect_error(ChangedOnDisk, "打开后已更新", saved_copy.save, unopened, guard)
        expect_error(ChangedOnDisk, "保存前出现", saved_copy.save, unopened)
        assert unopened.read_bytes() == after
        prior = saved_copy.save(unopened, snapshot(unopened))
        assert prior.read_bytes() == after and unopened.read_bytes() == before
        invalid = root / "损坏.srm"
        invalid.write_bytes(b"invalid")
        expect_error(InvalidSave, "32,768", Document.load, invalid, catalog, atlas.areas)
        assert not (target / invalid.name).exists()
    print("PASS Windows writes, backup copies and concurrent numbering, restore, write refusal and external updates")


if __name__ == "__main__":
    rom_path, before_path, after_path, fresh_path = map(Path, sys.argv[1:])
    catalog = Catalog.load(rom_path)
    atlas = Atlas(catalog)
    before, after, fresh = (p.read_bytes() for p in (before_path, after_path, fresh_path))
    format_checks(catalog, atlas, before, after, fresh)
    event_checks(catalog, atlas, before, after)
    file_checks(catalog, atlas, before, after)
