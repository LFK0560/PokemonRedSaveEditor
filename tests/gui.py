"""Exercise the actual Qt windows and controls on Windows using temporary saves."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editor.forms import ItemDialog, MonDialog
from editor.map_view import FloorDialog, ROLE
from editor.save import MAIN_SUM, PLAYER, Entry, Save, checksum
from editor.style import RED, STYLES
from editor.window import MainWindow


def click(button):
    assert button.isVisible() and button.isEnabled(), button.objectName()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def modal(action, kind, fill):
    problems = []
    visited = []

    def respond():
        window = QApplication.activeModalWidget()
        try:
            assert isinstance(window, kind), type(window)
            visited.append(window)
            fill(window)
        except BaseException as exc:
            problems.append(exc)
            if window:
                window.reject()

    QTimer.singleShot(20, respond)
    action()
    QApplication.processEvents()
    if problems:
        raise problems[0]
    assert len(visited) == 1


def choice(widget, value):
    i = widget.findData(value)
    assert i >= 0
    widget.setCurrentIndex(i)


def set_values(fields, values):
    for field, value in zip(fields, values, strict=True):
        field.setValue(value)


def add_mon(window, box, species):
    panel = window.mons
    panel.location.setCurrentIndex(0 if box is None else box + 1)
    model = window.document.model
    count = model.count(box)

    def fill(dialog):
        choice(dialog.species, species)
        assert all(not field.isEnabled() for field in dialog.stats)
        if box is None:
            assert dialog.formula.isChecked()
            dialog.level.setValue(12)
            assert dialog.hp.value() == dialog.stats[0].value() > 20
        click(dialog.accept_button)
        assert not dialog.isVisible()

    modal(lambda: click(panel.add), MonDialog, fill)
    assert panel.table.rowCount() == count + 1
    mon = model.read_mon(box, count)
    assert mon.species == species and mon.level == (12 if box is None else 5)


def edit_mon(window):
    model = window.document.model
    panel = window.mons
    panel.location.setCurrentIndex(0)
    panel.table.selectRow(0)
    old = model.read_mon(None, 0)
    moves = (0x35, 0x2D, 0x49, 0x4B)
    pp = (17, 39, 7, 26)
    ups = (3, 0, 2, 1)
    iv = (15, 14, 13, 12)
    effort = (65535, 123, 456, 789, 3456)
    stats = (240, 301, 260, 377, 290)

    def fill(dialog):
        assert tuple(field.value() for field in dialog.stats) == old.stats
        dialog.level.setValue(52)
        assert tuple(field.value() for field in dialog.stats) == old.stats
        dialog.name.setText("测试妙蛙种子")
        click(dialog.accept_button)
        assert dialog.error.isVisible() and "10 字节" in dialog.error.text()
        dialog.name.setText("测试妙蛙种")
        assert "10 / 10 字节" in dialog.name_count.text()
        dialog.hp.setValue(130)
        choice(dialog.status, 64)
        for field, move in zip(dialog.move, moves, strict=True):
            assert not field.model().item(field.findData(0xA5)).isEnabled()
            choice(field, move)
        first = dialog.move[0]
        assert first.model().item(first.currentIndex()).foreground().color() == QColor(RED)
        assert RED in first.styleSheet() and "均无" in dialog.move_reason[0].text()
        set_values(dialog.iv, iv)
        assert dialog.hp_dv.text() == "10（算出）"
        set_values(dialog.effort, effort)
        set_values(dialog.stats, stats)
        set_values(dialog.ups, ups)
        set_values(dialog.pp, pp)
        click(dialog.accept_button)
        assert not dialog.isVisible()

    modal(lambda: click(panel.edit), MonDialog, fill)
    mon = model.read_mon(None, 0)
    assert mon.nickname == "测试妙蛙种" and mon.level == 52 and mon.hp == 130 and mon.status == 64
    assert mon.experience == model.catalog.experience(mon.species, 52)
    assert (mon.moves, mon.pp, mon.pp_ups, mon.iv, mon.effort, mon.stats) == (moves, pp, ups, iv, effort, stats)
    click(window.save_button)
    saved = window.document.path.read_bytes()
    assert Save(model.catalog, saved, model.map_ids).read_mon(None, 0) == mon

    def formula(dialog):
        stored = tuple(field.value() for field in dialog.stats)
        assert stored == stats
        click(dialog.formula)
        predicted = model.catalog.stats(mon.species, mon.level, iv, effort)
        assert predicted == tuple(field.value() for field in dialog.stats)
        assert all(not field.isEnabled() for field in dialog.stats)
        click(dialog.accept_button)
        assert not dialog.isVisible()

    modal(lambda: click(panel.edit), MonDialog, formula)
    assert model.read_mon(None, 0).stats == model.catalog.stats(mon.species, mon.level, iv, effort)
    click(window.save_button)
    print("PASS native Qt dialogs: every requested field, red and disabled moves, manual and formula stats, on-disk record")


def edit_items(window):
    panel = window.items
    model = window.document.model
    window.pages.setCurrentWidget(panel)
    for pc in (False, True):
        panel.location.setCurrentIndex(int(pc))
        start = len(model.items(pc))

        def fill(dialog):
            choice(dialog.item, 0x14)
            assert not dialog.item.model().item(dialog.item.findData(7)).isEnabled()
            assert (dialog.quantity.minimum(), dialog.quantity.maximum()) == (1, 99)
            dialog.quantity.setValue(99)
            click(dialog.accept_button)
            assert not dialog.isVisible()

        modal(lambda: click(panel.add), ItemDialog, fill)
        assert model.items(pc)[start] == Entry(0x14, 99)
        panel.table.selectRow(start)

        def replace_item(dialog):
            choice(dialog.item, 0x3B)
            assert RED in dialog.item.styleSheet()
            dialog.quantity.setValue(1)
            click(dialog.accept_button)
            assert not dialog.isVisible()

        modal(lambda: click(panel.edit), ItemDialog, replace_item)
        assert model.items(pc)[start] == Entry(0x3B, 1)
        click(panel.remove)
        assert len(model.items(pc)) == start
        modal(lambda: click(panel.add), ItemDialog, fill)
    click(window.save_button)
    assert not model.dirty
    print("PASS native Qt bag and PC item add, replace, quantity, red and disabled choices, removal and save")


def map_checks(window):
    page = window.maps
    window.pages.setCurrentWidget(window.map_slot)
    page.show_overview()
    QApplication.processEvents()
    pewter = next(point for point in page.atlas.overview if 2 in point.ids)
    world = page.world_canvas
    view = page.overview_canvas
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(pewter.x, pewter.y))
    assert page.canvas is world and page.area == 2
    initial_zoom = world.transform().m11()
    world.zoom(1.22)
    assert world.transform().m11() > initial_zoom
    ax, ay = page.atlas.positions[2]
    entrance = next(w for w in page.atlas.areas[2].warps if w.map_id == 0x34)
    x, y = ax + entrance.x * 16 + 8, ay + entrance.y * 16 + 8
    world.centerOn(x, y)

    def upstairs(dialog):
        assert {dialog.floors.item(i).text() for i in range(dialog.floors.count())} == {"1F", "2F"}
        dialog.floors.setCurrentRow(1)
        click(dialog.findChild(QPushButton, "openFloor"))

    modal(lambda: QTest.mouseClick(world.viewport(), Qt.MouseButton.LeftButton,
                                   pos=world.mapFromScene(x, y)), FloorDialog, upstairs)
    assert page.area == 0x35
    view = page.floor_canvas
    person = page.index.by_key[0x35, "3"]
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.mapFromScene(person.x * 16 + 8, person.y * 16 + 8))
    assert page.open_event == person
    assert page.target_state.text() == "可重复互动" and page.reset_button.isEnabled()
    page.filter.setText("36:1")
    target = page.list.item(0)
    assert tuple(target.data(ROLE)) == (0x36, "1")
    QTest.mouseClick(page.list.viewport(), Qt.MouseButton.LeftButton, pos=page.list.visualItemRect(target).center())
    assert page.open_event == page.index.by_key[0x36, "1"]
    assert page.reset_button.isEnabled() and "徽章" in page.reason.text()
    page.filter.clear()
    model = window.document.model
    first, second = (page.index.by_key[k] for k in ((0xD7, "H28"), (0xD8, "H15")))
    # Set both hidden markers in the temporary fixture to exercise independent
    # selection through the two rendered floors at exactly the same pixels.
    for e in (first, second):
        for offset, mask in e.flags:
            model.data[offset] |= mask
    model.data[MAIN_SUM] = checksum(model.data, PLAYER, MAIN_SUM)
    window.refresh()
    for e in (first, second):
        page.show_floor(e.map_id)
        view = page.floor_canvas
        position = view.mapFromScene(e.x * 16 + 8, e.y * 16 + 8)
        raw = bytes(model.data)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=position)
        assert page.open_event == e and page.reset_button.isEnabled()
        click(page.reset_button)
        assert page.target_state.text() == "可触发"
        assert {i for i, (a, b) in enumerate(zip(raw, model.data)) if a != b} == {e.flags[0][0], MAIN_SUM}
    click(window.save_button)
    print("PASS native Qt overview, detailed map, floor picker, original marker, open leader and same-position floor targets")


def checks(rom, before, after, fresh):
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLES)
    window = MainWindow()
    window.show()
    app.processEvents()
    with TemporaryDirectory(prefix="口袋妖怪红_界面_") as folder:
        root = Path(folder)
        assert window.load_rom(rom)
        assert not window.save_button.isEnabled()
        broken = root / "截断档.srm"
        broken.write_bytes(b"truncated")

        def invalid(dialog):
            assert "32,768" in dialog.text()
            click(dialog.buttons()[0])

        modal(lambda: window.load_save(broken), QMessageBox, invalid)
        assert not window.save_button.isEnabled()
        for original, name in ((after, "复位后[简].srm"), (before, "复位前[简].srm.bak"), (fresh, "新开档[赤红].srm")):
            path = root / name
            path.write_bytes(original.read_bytes())
            assert window.load_save(path)
            assert name in window.doc_label.text()
            assert window.last_backup.read_bytes() == original.read_bytes()
            if original == after:
                raw = bytes(window.document.model.data)

                def full(dialog):
                    assert "6 / 6" in dialog.text()
                    click(dialog.buttons()[0])

                modal(lambda: click(window.mons.add), QMessageBox, full)
                assert raw == window.document.model.data
        model = window.document.model
        assert not model.initialized and "赤红" in window.doc_label.text()
        add_mon(window, None, 0x99)
        add_mon(window, model.current_box, 0xB0)
        add_mon(window, (model.current_box + 1) % 12, 0xB1)
        assert model.initialized
        print("PASS native Qt import diagnostics, sample copies and fresh Chinese save, full capacity and three add destinations")
        edit_mon(window)
        edit_items(window)
        map_checks(window)
    window.close()


if __name__ == "__main__":
    checks(*map(Path, sys.argv[1:]))
