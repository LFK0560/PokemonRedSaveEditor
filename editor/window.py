from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QMessageBox, QProgressBar,
    QPushButton, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .events import EventIndex
from .files import Document, snapshot
from .forms import ItemDialog, MonDialog
from .map_view import MapPage
from .maps import Atlas
from .rom import Catalog
from .save import BAG, PC_ITEMS, STATUS
from .style import RED, STYLES, app_icon, label, message


TITLE = "口袋妖怪红存档修改器"


def button(text, name, handler, *, primary=False, link=False):
    result = QPushButton(text)
    result.setObjectName(name)
    if primary:
        result.setProperty("primary", True)
    if link:
        result.setProperty("link", True)
    result.clicked.connect(handler)
    return result


def table(headers, name):
    grid = QTableWidget(0, len(headers))
    grid.setObjectName(name)
    grid.setHorizontalHeaderLabels(headers)
    grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    grid.setAlternatingRowColors(True)
    grid.setShowGrid(False)
    grid.verticalHeader().hide()
    grid.verticalHeader().setDefaultSectionSize(36)
    grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    grid.horizontalHeader().setStretchLastSection(True)
    return grid


class EditList(QWidget):
    def __init__(self, title, applied, is_mon):
        super().__init__()
        self.model = None
        self.applied = applied
        self.is_mon = is_mon
        p = QVBoxLayout(self)
        p.setContentsMargins(20, 17, 20, 15)
        p.setSpacing(13)
        header = QHBoxLayout()
        self.title = label(title, "heading")
        header.addWidget(self.title, 1)
        self.location = QComboBox()
        self.location.setObjectName("monLocation" if is_mon else "itemLocation")
        self.location.setMinimumWidth(205)
        if is_mon:
            self.location.addItem("随身队伍", None)
            for i in range(12):
                self.location.addItem(f"精灵箱 {i + 1:02d}", i)
        else:
            self.location.addItem("背包", False)
            self.location.addItem("PC 道具储存处", True)
        self.location.currentIndexChanged.connect(lambda _: self.refresh())
        header.addWidget(self.location)
        p.addLayout(header)
        toolbar = QHBoxLayout()
        self.capacity = label("", "pill")
        self.fill = QProgressBar()
        self.fill.setTextVisible(False)
        self.fill.setFixedSize(95, 6)
        prefix = "Mon" if is_mon else "Item"
        noun = "精灵" if is_mon else "道具"
        self.add = button("添加" + noun, "add" + prefix, self.add_row, primary=True)
        self.edit = button("编辑所选", "edit" + prefix, self.edit_row)
        self.remove = button("移除所选", "removeItem", self.remove_row) if not is_mon else None
        toolbar.addWidget(self.capacity)
        toolbar.addWidget(self.fill)
        toolbar.addStretch(1)
        if self.remove:
            toolbar.addWidget(self.remove)
        toolbar.addWidget(self.edit)
        toolbar.addWidget(self.add)
        p.addLayout(toolbar)
        headers = ("位置", "昵称", "种类", "等级", "当前 / 最大 HP", "状态", "招式") if is_mon else ("位置", "ID", "道具", "数量", "行为")
        self.table = table(headers, "pokemonTable" if is_mon else "itemsTable")
        self.table.itemDoubleClicked.connect(self.edit_row)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        p.addWidget(self.table, 1)
        self.note = label("", "hint", True)
        p.addWidget(self.note)
        self.set_model(None)

    def set_model(self, model):
        self.model = model
        self.location.setEnabled(model is not None)
        self.refresh()

    def selection_changed(self):
        selected = self.table.currentRow() >= 0 and bool(self.table.selectedItems())
        self.edit.setEnabled(selected)
        if self.remove:
            self.remove.setEnabled(selected)

    def refresh(self):
        m = self.model
        current = self.table.currentRow()
        self.table.setRowCount(0)
        self.edit.setEnabled(False)
        self.add.setEnabled(m is not None)
        if self.remove:
            self.remove.setEnabled(False)
        if m is None:
            self.capacity.setText("等待导入存档")
            self.fill.setValue(0)
            self.note.setText("选择受支持的 ROM 后，打开游戏内保存的 .srm 文件。")
            return
        location = self.location.currentData()
        if self.is_mon:
            self.location.setItemText(0, "随身队伍")
            for i in range(12):
                self.location.setItemText(i + 1, f"精灵箱 {i + 1:02d}" + (" · 当前箱" if i == m.current_box else ""))
            capacity = m.layout(location).capacity
            count = m.count(location)
            self.title.setText(self.location.currentText())
            self.table.setRowCount(count)
            for row in range(count):
                mon = m.read_mon(location, row)
                species = m.catalog.species[mon.species]
                names = []
                unusual = False
                for move in mon.moves:
                    if move:
                        names.append(m.catalog.moves.get(move, f"{move:02X}"))
                        unusual |= m.catalog.move_rule(mon.species, mon.level, move)[0] == "unusual"
                self.put_row(row, (row + 1, mon.nickname, species.name, mon.level, f"{mon.hp} / {mon.stats[0]}",
                                   STATUS.get(mon.status, f"未知 {mon.status:02X}"), "、".join(names)), unusual)
            text = "双击精灵可编辑。能力值默认显示存档原值。"
            if location is not None:
                text = "箱内能力值为计算预览。取出时游戏会根据等级、个体值和努力值重算。"
                if location != m.current_box and not m.initialized:
                    text += " 该存档从未换箱，首次添加会初始化其余箱子。"
        else:
            entries = m.items(location)
            capacity = (PC_ITEMS if location else BAG)[1]
            count = len(entries)
            self.title.setText(self.location.currentText())
            self.table.setRowCount(count)
            for row, entry in enumerate(entries):
                item = m.catalog.items[entry.id]
                others = [other for i, other in enumerate(entries) if i != row]
                state, reason = m.item_rule(location, others, entry.id, entry.qty)
                behavior = "关键道具" if item.key else "普通道具"
                if state == "unusual":
                    behavior = reason
                elif state == "disabled":
                    behavior = "原档条目 · " + reason
                self.put_row(row, (row + 1, f"{entry.id:02X}", item.name, entry.qty, behavior),
                             state in ("unusual", "disabled"))
            text = "每组 1–99。剧情的领取和通路记录按游戏原值保留。"
        if count:
            self.table.selectRow(min(max(0, current), count - 1))
        self.capacity.setText(f"{count} / {capacity}  ·  剩余 {capacity - count}")
        self.fill.setRange(0, capacity)
        self.fill.setValue(count)
        self.note.setText(text)

    def put_row(self, row, values, red):
        for i, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            if red and (i == 6 if self.is_mon else i in (2, 4)):
                cell.setForeground(QColor(RED))
            cell.setToolTip(str(value))
            self.table.setItem(row, i, cell)

    def add_row(self):
        location = self.location.currentData()
        if self.is_mon:
            count, maximum = self.model.count(location), self.model.layout(location).capacity
        else:
            count, maximum = len(self.model.items(location)), (PC_ITEMS if location else BAG)[1]
        if count >= maximum:
            message(self, "容量已满", f"{self.location.currentText()}已满（{count} / {maximum}）。")
            return
        self.open_dialog(location, None)

    def edit_row(self, *_):
        row = self.table.currentRow()
        if row >= 0:
            self.open_dialog(self.location.currentData(), row)

    def open_dialog(self, location, row):
        m = self.model
        original = bytes(m.data)
        dialog = MonDialog(self, m, location, row) if self.is_mon else ItemDialog(self, m, location, row)
        accepted = dialog.exec()
        dialog.deleteLater()
        if accepted and original != m.data:
            self.applied(f"{'添加' if row is None else '编辑'}{'精灵' if self.is_mon else '道具'} · {self.location.currentText()}")

    def remove_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        pc = self.location.currentData()
        entry = self.model.items(pc)[row]
        name = self.model.catalog.items[entry.id].name
        try:
            self.model.apply_items(pc, row, None)
        except ValueError as exc:
            message(self, "无法移除", exc)
        else:
            self.applied(f"移除 {name} ×{entry.qty} · {self.location.currentText()}")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.resize(1236, 825)
        self.setMinimumSize(965, 675)
        self.setWindowIcon(app_icon())
        self.setObjectName("window")
        self.settings = QSettings("OfflineTools", "PokemonRedSaveEditor")
        self.rom_path = None
        self.catalog = None
        self.atlas = None
        self.document = None
        self.changes = []
        self.last_backup = None
        self.build()
        self.refresh()

    def build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QWidget()
        top.setObjectName("masthead")
        l = QHBoxLayout(top)
        l.setContentsMargins(24, 17, 24, 16)
        t = QVBoxLayout()
        name = label(TITLE, "appTitle")
        t.addWidget(name)
        t.addWidget(label("简体中文版 · Windows 离线", "muted"))
        l.addLayout(t, 1)
        self.rom_button = button("选择 ROM…", "openRom", self.choose_rom)
        self.open_button = button("导入存档…", "openSave", self.choose_save)
        self.save_as_button = button("另存为…", "saveAs", self.save_as)
        self.save_button = button("保存", "save", self.save_file, primary=True)
        for w in (self.rom_button, self.open_button, self.save_as_button, self.save_button):
            l.addWidget(w)
        outer.addWidget(top)

        panel = QWidget()
        panel.setObjectName("context")
        c = QHBoxLayout(panel)
        c.setContentsMargins(24, 8, 24, 8)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.rom_label = label("", "muted")
        self.rom_label.setObjectName("romPath")
        self.doc_label = label("", "section")
        self.doc_label.setObjectName("savePath")
        info.addWidget(self.doc_label)
        info.addWidget(self.rom_label)
        c.addLayout(info, 1)
        self.backup_button = button("查看备份", "showBackup", self.open_backup, link=True)
        self.log_button = button("查看改动", "showChanges", self.show_changes, link=True)
        c.addWidget(self.backup_button)
        c.addWidget(self.log_button)
        self.dirty_label = label("", "pill")
        self.dirty_label.setObjectName("dirtyState")
        self.dirty_label.setStyleSheet("background:#e4efe8; padding:5px 9px; border-radius:6px; font-weight:700;")
        c.addWidget(self.dirty_label)
        outer.addWidget(panel)

        work = QVBoxLayout()
        work.setContentsMargins(24, 4, 24, 10)
        work.setSpacing(9)
        self.pages = QTabWidget()
        self.pages.setObjectName("pages")
        self.mons = EditList("队伍与精灵箱", self.applied, True)
        self.items = EditList("道具", self.applied, False)
        self.mons.setObjectName("surface")
        self.items.setObjectName("surface")
        self.map_slot = QStackedWidget()
        self.map_empty = label("选择 ROM 后可浏览城镇、道路和各楼层。", "hint", True)
        self.map_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.map_slot.addWidget(self.map_empty)
        self.maps = MapPage(self.applied)
        self.map_slot.addWidget(self.maps)
        self.pages.addTab(self.mons, "队伍与精灵箱")
        self.pages.addTab(self.items, "道具")
        self.pages.addTab(self.map_slot, "地图与事件")
        work.addWidget(self.pages, 1)
        self.status = label("请选择本地 ROM。", "muted")
        self.status.setObjectName("fileStatus")
        self.status.setStyleSheet("color:#526860;")
        self.status.setWordWrap(True)
        work.addWidget(self.status)
        outer.addLayout(work, 1)
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.choose_save)
        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(self.save_file)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self.save_as)

    def tell(self, text):
        self.status.setText(text)

    def dialog(self, title, key, filters, save=False, suggested=""):
        default_folder = self.rom_path.parent if self.rom_path else Path.home()
        directory = str(self.settings.value(key, str(default_folder)))
        selector = QFileDialog(self, title, directory, filters)
        selector.setObjectName("filePicker")
        selector.setLabelText(QFileDialog.DialogLabel.FileName, "文件名")
        selector.setLabelText(QFileDialog.DialogLabel.Accept, "保存" if save else "打开")
        selector.setLabelText(QFileDialog.DialogLabel.Reject, "取消")
        selector.setAcceptMode(QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen)
        selector.setFileMode(QFileDialog.FileMode.AnyFile if save else QFileDialog.FileMode.ExistingFile)
        if save:
            selector.setOption(QFileDialog.Option.DontConfirmOverwrite)
            selector.setDefaultSuffix("srm")
            if suggested:
                selector.selectFile(suggested)
        if selector.exec():
            path = Path(selector.selectedFiles()[0])
            self.settings.setValue(key, str(path.parent))
        else:
            path = None
        selector.deleteLater()
        return path

    def choose_rom(self):
        if not self.allow_leave():
            return
        path = self.dialog("选择《口袋妖怪红》的本地 ROM", "romFolder", "Game Boy ROM (*.gb *.gbc);;所有文件 (*)")
        if path:
            self.load_rom(path)

    def load_rom(self, path: Path):
        try:
            catalog = Catalog.load(path)
            atlas = Atlas(catalog)
            index = EventIndex(atlas)
        except (OSError, ValueError) as exc:
            self.tell(f"ROM 无法打开 · {exc}")
            message(self, "ROM 校验未通过", exc)
            return False
        self.rom_path = path.resolve()
        self.catalog = catalog
        self.atlas = atlas
        self.maps.setup(atlas, index)
        self.map_slot.setCurrentWidget(self.maps)
        self.document = None
        self.changes.clear()
        self.last_backup = None
        self.refresh()
        self.tell("ROM 校验通过。可导入 .srm 存档，也可以先浏览地图。")
        return True

    def choose_save(self):
        if not self.catalog or not self.allow_leave():
            return
        path = self.dialog("导入《口袋妖怪红》存档", "saveFolder", "游戏存档 (*.srm *.srm.bak);;所有文件 (*)")
        if path:
            self.load_save(path)

    def load_save(self, path: Path):
        try:
            document = Document.load(path, self.catalog, self.atlas.areas)
        except (OSError, ValueError) as exc:
            self.tell(f"导入失败 · {exc}")
            message(self, "无法导入存档", exc)
            return False
        self.document = document
        self.changes.clear()
        self.last_backup = document.import_backup
        self.mons.location.setCurrentIndex(0)
        self.items.location.setCurrentIndex(0)
        self.refresh()
        self.tell(f"已生成导入备份 · {self.last_backup}")
        return True

    def refresh(self):
        doc = self.document
        model = doc.model if doc else None
        self.rom_label.setText(f"ROM · {self.rom_path.name}  |  SHA-256 已核对" if self.rom_path else "尚未选择 ROM")
        self.rom_label.setToolTip(str(self.rom_path) if self.rom_path else "")
        if doc:
            map_name = self.atlas.areas[model.map_id].title
            self.doc_label.setText(f"{model.player}  ·  {map_name}  |  {doc.path.name}")
            self.doc_label.setToolTip(str(doc.path))
        else:
            self.doc_label.setText("尚未导入存档")
        self.open_button.setEnabled(self.catalog is not None)
        enabled = doc is not None
        self.save_button.setEnabled(enabled)
        self.save_as_button.setEnabled(enabled)
        self.backup_button.setEnabled(self.last_backup is not None)
        self.log_button.setEnabled(bool(model and model.dirty))
        self.dirty_label.setText("有待保存改动" if model and model.dirty else "存档已导入" if model else "未导入")
        self.mons.set_model(model)
        self.items.set_model(model)
        self.maps.set_save(model)

    def applied(self, summary):
        self.changes.append(summary)
        self.refresh()
        self.tell(f"{summary} · 已应用到内存")

    def allow_leave(self):
        if not self.document or not self.document.model.dirty:
            return True
        box = QMessageBox(QMessageBox.Icon.Question, "有待保存的改动", "先保存当前存档的改动？", parent=self)
        save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("丢弃改动", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("返回", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() == save:
            return self.save_file()
        return box.clickedButton() == discard

    def save_file(self):
        if not self.document:
            return False
        return self.write()

    def save_as(self):
        if not self.document:
            return False
        current = self.document.path
        raw_name = current.name[:-8] if current.name.lower().endswith(".srm.bak") else current.stem
        path = self.dialog("另存存档", "saveFolder", "游戏存档 (*.srm);;所有文件 (*)",
                           save=True, suggested=raw_name + "_编辑.srm")
        if not path:
            return False
        try:
            expected = snapshot(path.resolve()) if path.resolve() != current and path.exists() else None
        except (OSError, ValueError) as exc:
            message(self, "无法核对另存目标", exc)
            return False
        if expected:
            box = QMessageBox(QMessageBox.Icon.Question, "覆盖已有存档", f"覆盖「{path.name}」？程序会先备份该文件。", parent=self)
            yes = box.addButton("备份并覆盖", QMessageBox.ButtonRole.AcceptRole)
            cancel = box.addButton("返回", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(cancel)
            box.exec()
            if box.clickedButton() != yes:
                return False
        return self.write(path, expected)

    def write(self, path=None, expected=None):
        try:
            previous = self.document.save(path, expected)
        except (OSError, ValueError) as exc:
            self.tell(f"保存失败 · {exc}")
            message(self, "保存失败 · 编辑仍在内存中", exc)
            return False
        self.changes.clear()
        if previous:
            self.last_backup = previous
        self.refresh()
        self.tell(f"已保存 · {self.document.path}" + (f"\n覆盖前备份 · {previous.name}" if previous else ""))
        return True

    def open_backup(self):
        if self.last_backup:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_backup.parent)))

    def show_changes(self):
        doc = self.document
        if not doc or not doc.model.dirty:
            return
        d = QDialog(self)
        d.setWindowTitle("待保存改动")
        d.resize(480, 340)
        panel = QVBoxLayout(d)
        count = sum(a != b for a, b in zip(doc.model.original, doc.model.data))
        panel.addWidget(label(f"待保存改动 · {count} 字节", "heading"))
        rows = QListWidget()
        rows.addItems(self.changes)
        panel.addWidget(rows, 1)
        panel.addWidget(button("关闭", "closeChanges", d.accept))
        d.exec()
        d.deleteLater()

    def closeEvent(self, event):
        if self.allow_leave():
            event.accept()
        else:
            event.ignore()


def launch():
    app = QApplication([])
    app.setApplicationName(TITLE)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLES)
    window = MainWindow()
    window.show()
    return app.exec()
