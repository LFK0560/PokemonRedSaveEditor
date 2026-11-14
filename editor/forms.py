from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout,
)

from .events import QUEST_FLAGS, flag, in_save
from .rom import hp_iv
from .save import EVENT_FLAGS, Entry, STAT_NAMES, STATUS, Save
from .style import GOLD, RED, label


class Choice(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(13)
        self.setModel(QStandardItemModel(self))
        self.currentIndexChanged.connect(self.update_color)

    def options(self, rows, selected=None):
        self.blockSignals(True)
        self.clear()
        for id_, text, state, reason in rows:
            item = QStandardItem(text)
            item.setData(id_, Qt.ItemDataRole.UserRole)
            item.setData(state, Qt.ItemDataRole.UserRole + 1)
            item.setToolTip(reason)
            if state == "unusual":
                item.setForeground(QColor(RED))
            elif state == "unknown":
                item.setForeground(QColor(GOLD))
            if state == "disabled":
                item.setEnabled(False)
            self.model().appendRow(item)
        if selected is not None:
            self.setCurrentIndex(self.findData(selected))
        elif self.count():
            for i in range(self.count()):
                if self.model().item(i).isEnabled():
                    self.setCurrentIndex(i)
                    break
        self.blockSignals(False)
        self.update_color()

    def update_color(self):
        state = self.currentData(Qt.ItemDataRole.UserRole + 1)
        color = RED if state == "unusual" else GOLD if state == "unknown" else "#192b2a"
        self.setStyleSheet(f"QComboBox {{ color: {color}; }}")
        self.setToolTip(self.currentData(Qt.ItemDataRole.ToolTipRole) or "")


def spin(name, high, low=0):
    widget = QSpinBox()
    widget.setObjectName(name)
    widget.setRange(low, high)
    widget.setKeyboardTracking(False)
    return widget


class EditorDialog(QDialog):
    def __init__(self, parent, title, width):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(23, 19, 23, 19)
        self.outer.setSpacing(12)
        self.outer.addWidget(label(title, "heading"))
        self.error = label("", "warning", True)
        self.error.hide()
        self.accept_button = QPushButton("应用编辑")
        self.accept_button.setObjectName("applyEdit")
        self.accept_button.setProperty("primary", True)
        self.accept_button.clicked.connect(self.apply)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)

    def footer(self):
        self.outer.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.accept_button)
        self.outer.addLayout(buttons)

    def fail(self, reason):
        self.error.setText(str(reason))
        self.error.show()

    def apply(self):
        raise NotImplementedError


class MonDialog(EditorDialog):
    def __init__(self, parent, save: Save, box: int | None, slot: int | None):
        target = "随身队伍" if box is None else f"精灵箱 {box + 1:02d}"
        super().__init__(parent, f"{'添加精灵' if slot is None else '编辑精灵'} · {target}", 790)
        self.save = save
        self.catalog = save.catalog
        self.box = box
        self.slot = slot
        self.loading = True
        self.mon = save.new_mon(self.catalog.by_dex[0].id) if slot is None else save.read_mon(box, slot)
        top = QGridLayout()
        top.setHorizontalSpacing(15)
        top.setVerticalSpacing(8)
        self.species = Choice()
        self.species.setObjectName("monSpecies")
        self.species.options(self.species_rows(self.mon.level), self.mon.species)
        self.species.setEnabled(slot is None)
        self.name = QLineEdit()
        self.name.setObjectName("monNickname")
        self.level = spin("monLevel", 100, 1)
        self.hp = spin("monHp", 999)
        self.status = Choice()
        self.status.setObjectName("monStatus")
        self.status.options([(k, text, "normal", "") for k, text in STATUS.items()])
        for col, (name, field) in enumerate([("种类", self.species), ("昵称", self.name),
                                              ("等级", self.level), ("当前 HP", self.hp), ("异常状态", self.status)]):
            question = QLabel(name)
            question.setBuddy(field)
            top.addWidget(question, 0, col)
            top.addWidget(field, 1, col)
        top.setColumnStretch(0, 4)
        top.setColumnStretch(1, 4)
        top.setColumnStretch(4, 3)
        self.outer.addLayout(top)
        self.name_count = label("", "muted")
        self.outer.addWidget(self.name_count)
        self.make_moves()
        self.make_stats()
        self.footer()
        self.populate(self.mon)
        self.species.currentIndexChanged.connect(self.change_species)
        self.level.valueChanged.connect(self.change_level)
        self.name.textChanged.connect(self.nickname_info)

    def make_moves(self):
        box = QGroupBox("招式")
        layout = QGridLayout(box)
        self.move = []
        self.pp = []
        self.ups = []
        self.pp_limit = []
        self.move_reason = []
        for col, value in enumerate(("招式", "当前 PP", "PP 提升", "上限", "习得途径")):
            layout.addWidget(label(value, "muted"), 0, col + 1)
        for i in range(4):
            self.move.append(Choice())
            self.move[i].setObjectName(f"move{i + 1}")
            self.pp.append(spin(f"movePP{i + 1}", 63))
            self.ups.append(spin(f"moveUps{i + 1}", 3))
            self.pp_limit.append(label("", "muted"))
            reason = label("", "muted", True)
            reason.setMinimumWidth(220)
            self.move_reason.append(reason)
            layout.addWidget(label(str(i + 1), "muted"), i + 1, 0)
            layout.addWidget(self.move[i], i + 1, 1)
            layout.addWidget(self.pp[i], i + 1, 2)
            layout.addWidget(self.ups[i], i + 1, 3)
            layout.addWidget(self.pp_limit[i], i + 1, 4)
            layout.addWidget(reason, i + 1, 5)
            self.move[i].currentIndexChanged.connect(lambda _, row=i: self.move_changed(row, True))
            self.ups[i].valueChanged.connect(lambda _, row=i: self.move_changed(row, False))
        layout.setColumnStretch(1, 3)
        layout.setColumnStretch(5, 4)
        self.outer.addWidget(box)

    def make_stats(self):
        box = QGroupBox("能力值 · 初代")
        panel = QVBoxLayout(box)
        self.stat_mode = QHBoxLayout()
        self.manual = QRadioButton("原值 / 手填")
        self.manual.setObjectName("manualStats")
        self.formula = QRadioButton("按游戏公式重算")
        self.formula.setObjectName("formulaStats")
        if self.box is None:
            self.stat_mode.addWidget(self.manual)
            self.stat_mode.addWidget(self.formula)
            self.stat_mode.addStretch(1)
            (self.formula if self.slot is None else self.manual).setChecked(True)
            panel.addLayout(self.stat_mode)
        else:
            panel.addWidget(label("箱子只保存等级、个体值、努力值和当前 HP。取出时游戏按这些值重算能力。", "muted", True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(11)
        grid.setVerticalSpacing(6)
        self.hp_dv = label()
        self.iv = [spin(f"dv{i + 1}", 15) for i in range(4)]
        self.effort = [spin(f"effort{i + 1}", 65535) for i in range(5)]
        self.stats = [spin(f"stat{i + 1}", 999) for i in range(5)]
        for row, value in enumerate(("个体值", "努力值 · Stat Exp", "能力值"), 1):
            grid.addWidget(label(value, "muted"), row, 0)
        for i, column in enumerate(STAT_NAMES):
            grid.addWidget(label("最大 HP" if i == 0 else column, "muted"), 0, i + 1)
            grid.addWidget(self.hp_dv if i == 0 else self.iv[i - 1], 1, i + 1)
            grid.addWidget(self.effort[i], 2, i + 1)
            grid.addWidget(self.stats[i], 3, i + 1)
        panel.addLayout(grid)
        if self.box is None:
            panel.addWidget(label("升级、进化、使用能力增强剂或从箱子取出时，游戏可能重算手填能力。", "muted", True))
        for field in (*self.iv, *self.effort):
            field.valueChanged.connect(self.update_stats)
        self.formula.toggled.connect(self.update_stats)
        self.outer.addWidget(box)

    def populate(self, mon):
        self.loading = True
        self.name.setText(mon.nickname)
        self.level.setValue(mon.level)
        self.hp.setValue(mon.hp)
        self.status.setCurrentIndex(self.status.findData(mon.status))
        for fields, values in ((self.iv, mon.iv), (self.effort, mon.effort), (self.stats, mon.stats)):
            for field, value in zip(fields, values, strict=True):
                field.setValue(value)
        self.rebuild_moves(mon.moves)
        for i in range(4):
            self.pp[i].setValue(mon.pp[i])
            self.ups[i].setValue(mon.pp_ups[i])
            self.move_changed(i, False)
        self.loading = False
        self.update_stats()
        self.nickname_info()

    def nickname_info(self):
        if self.name.text() == self.mon.nickname and self.slot is not None:
            self.name_count.setText("昵称保留原编码。修改时最多输入 10 字节（通常为 5 个汉字）。")
            return
        try:
            name = self.catalog.charset.nickname(self.name.text())
        except ValueError as exc:
            self.name_count.setText(str(exc))
        else:
            self.name_count.setText(f"昵称已用 {self.catalog.charset.string_end(name)} / 10 字节。")

    def rebuild_moves(self, selected):
        species = self.species.currentData()
        level = self.level.value()
        choices = [(m, f"{m:02X}  {name}" if m else name, *self.catalog.move_rule(species, level, m))
                   for m, name in self.catalog.moves.items()]
        for i, field in enumerate(self.move):
            field.options(choices, selected[i])

    def change_species(self):
        if self.loading:
            return
        self.mon = self.save.new_mon(self.species.currentData(), self.level.value())
        self.populate(self.mon)

    def change_level(self):
        if self.loading:
            return
        self.species.options(self.species_rows(self.level.value()), self.species.currentData())
        self.rebuild_moves([c.currentData() for c in self.move])
        for i in range(4):
            self.move_changed(i, False)
        self.update_stats()

    def species_rows(self, level):
        return [(s.id, f"#{s.dex:03d}  {s.name}", *self.catalog.species_rule(s.id, level))
                for s in self.catalog.by_dex]

    def move_changed(self, row, reset_pp):
        move = self.move[row].currentData()
        if move is None:
            return
        if reset_pp and not self.loading:
            self.ups[row].blockSignals(True)
            self.ups[row].setValue(0)
            self.ups[row].blockSignals(False)
            self.pp[row].setValue(self.catalog.base_pp[move])
        up = self.ups[row].value()
        maximum = self.catalog.max_pp(move, up)
        self.pp_limit[row].setText(str(maximum))
        self.ups[row].setEnabled(bool(move))
        self.pp[row].setEnabled(bool(move))
        state = self.move[row].currentData(Qt.ItemDataRole.UserRole + 1)
        self.move_reason[row].setText(self.move[row].currentData(Qt.ItemDataRole.ToolTipRole))
        self.move_reason[row].setStyleSheet("color: " + (RED if state == "unusual" else GOLD if state == "unknown" else "#526860"))

    def update_stats(self):
        if self.loading:
            return
        iv = tuple(field.value() for field in self.iv)
        self.hp_dv.setText(f"{hp_iv(iv)}（算出）")
        calculate = self.box is not None or self.formula.isChecked()
        for field in self.stats:
            field.setEnabled(not calculate)
        if calculate:
            was_full = self.hp.value() == self.stats[0].value()
            result = self.catalog.stats(self.species.currentData(), self.level.value(),
                                        iv, tuple(field.value() for field in self.effort))
            for field, value in zip(self.stats, result, strict=True):
                field.setValue(value)
            if self.slot is None and was_full:
                self.hp.setValue(result[0])

    def apply(self):
        mon = replace(
            self.mon, species=self.species.currentData(), level=self.level.value(), nickname=self.name.text(),
            hp=self.hp.value(), status=self.status.currentData(), moves=tuple(c.currentData() for c in self.move),
            pp=tuple(c.value() for c in self.pp), pp_ups=tuple(c.value() for c in self.ups),
            iv=tuple(c.value() for c in self.iv), effort=tuple(c.value() for c in self.effort),
            stats=tuple(c.value() for c in self.stats),
        )
        try:
            self.save.apply_mon(self.box, self.slot, mon)
        except (ValueError, KeyError) as exc:
            self.fail(exc)
        else:
            self.accept()


class ItemDialog(EditorDialog):
    def __init__(self, parent, save: Save, pc: bool, index: int | None):
        super().__init__(parent, f"{'添加道具' if index is None else '编辑道具'} · {'PC 道具储存处' if pc else '背包'}", 510)
        self.save, self.pc, self.index = save, pc, index
        self.other_entries = save.items(pc)
        old = self.other_entries.pop(index) if index is not None else None
        form = QFormLayout()
        self.item = Choice()
        self.item.setObjectName("itemId")
        self.quantity = spin("itemQuantity", 99, 1)
        self.quantity.setValue(old.qty if old else 1)
        self.result = label("", "hint", True)
        self.progress = label("", "muted", True)
        form.addRow("道具", self.item)
        form.addRow("组内数量", self.quantity)
        self.outer.addLayout(form)
        self.outer.addWidget(self.result)
        self.outer.addWidget(self.progress)
        self.footer()
        self.refresh_choices(old.id if old else 0x14)
        self.item.currentIndexChanged.connect(self.update_reason)
        self.quantity.valueChanged.connect(self.quantity_changed)

    def refresh_choices(self, selected):
        self.item.options([
            (item.id, f"{item.id:02X}  {item.name}", *self.save.item_rule(self.pc, self.other_entries, item.id, self.quantity.value()))
            for item in self.save.catalog.items.values()
        ], selected)
        self.update_reason()

    def quantity_changed(self):
        self.refresh_choices(self.item.currentData())

    def update_reason(self):
        item = self.item.currentData()
        if item is None:
            return
        state, reason = self.save.item_rule(self.pc, self.other_entries, item, self.quantity.value())
        self.result.setText(reason)
        self.result.setStyleSheet(f"color: {RED};" if state == "unusual" or state == "disabled" else "")
        self.accept_button.setEnabled(state != "disabled")
        if item in QUEST_FLAGS:
            bit, status = QUEST_FLAGS[item]
            active = in_save(self.save, flag(EVENT_FLAGS, bit))
            self.progress.setText(f"剧情记录「{status}」{'已设置' if active else '尚未设置'}。")
        else:
            self.progress.clear()

    def apply(self):
        try:
            self.save.apply_items(self.pc, self.index, Entry(self.item.currentData(), self.quantity.value()))
        except ValueError as exc:
            self.fail(exc)
        else:
            self.accept()
