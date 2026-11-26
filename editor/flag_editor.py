"""Direct event-bit editing and user-supplied map event associations."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .style import label


class FlagEditor(QDialog):
    def __init__(self, parent, save):
        super().__init__(parent)
        self.setWindowTitle("事件标记编辑")
        self.resize(720, 570)
        self.save = save
        self.buffer = bytearray(save.data)
        self.region = None
        self.loading = False
        self.changed = False
        outer = QVBoxLayout(self)
        outer.addWidget(label("直接设置或清除标记，应用后使用主窗口的保存或另存为。", "section", True))
        outer.addWidget(label("此页开放全部剧情位、对象显隐、隐藏道具及地图工作字节。位编号从 0 开始。", "muted", True))
        self.groups = QComboBox()
        p = save.profile
        for title, start, size in (("剧情事件 · 2560 位", p.event_flags, 320),
                                   ("对象显隐", p.toggle_flags, 74),
                                   ("隐藏道具", p.hidden_flags, 14),
                                   ("地图脚本工作区", p.event_work, 256)):
            self.groups.addItem(title, (start, size))
        self.groups.currentIndexChanged.connect(self.change_group)
        outer.addWidget(self.groups)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["文件偏移", "值", *[f"位 {i}" for i in range(8)]])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self.update_value)
        outer.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        apply = QPushButton("应用标记")
        apply.setProperty("primary", True)
        apply.clicked.connect(self.apply)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        outer.addLayout(buttons)
        self.change_group()

    def capture(self):
        if self.region is None:
            return
        start, size = self.region
        for row in range(size):
            self.buffer[start+row] = sum(1 << bit for bit in range(8)
                                       if self.table.item(row, bit+2).checkState() == Qt.CheckState.Checked)

    def change_group(self):
        self.capture()
        self.region = self.groups.currentData()
        start, size = self.region
        self.loading = True
        self.table.setRowCount(size)
        for row in range(size):
            value = self.buffer[start+row]
            for col, text in ((0, f"0x{start+row:04X}"), (1, f"{value:02X}")):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(row, col, item)
            for bit in range(8):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if value & 1 << bit else Qt.CheckState.Unchecked)
                item.setToolTip(f"编号 {row*8+bit} / 0x{row*8+bit:03X}")
                self.table.setItem(row, bit+2, item)
        self.loading = False

    def update_value(self, item):
        if self.loading or item.column() < 2:
            return
        row = item.row()
        value = sum(1 << bit for bit in range(8)
                    if self.table.item(row, bit+2).checkState() == Qt.CheckState.Checked)
        self.table.item(row, 1).setText(f"{value:02X}")

    def apply(self):
        self.capture()
        self.changed = self.save.set_bytes((i, v) for i, v in enumerate(self.buffer) if v != self.save.data[i])
        self.accept()


class BindingEditor(QDialog):
    def __init__(self, parent, event, save):
        super().__init__(parent)
        self.setWindowTitle("关联标记 · " + event.name)
        self.setMinimumWidth(580)
        self.bindings = None
        self.save = save
        outer = QVBoxLayout(self)
        outer.addWidget(label("事件关联标记", "section"))
        outer.addWidget(label("填写存档中的文件偏移和掩码。复位将清除这些位，其他位保留。", "muted", True))
        outer.addWidget(label("格式：0x偏移:0x掩码，多项用逗号分隔。可从「事件标记」页查看偏移。", "muted", True))
        self.input = QLineEdit(", ".join(f"0x{save.profile.reference_offset(offset):04X}:0x{mask:02X}" for offset, mask in event.flags))
        outer.addWidget(self.input)
        self.error = label("", "warning", True)
        outer.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        apply = QPushButton("保存关联")
        apply.clicked.connect(self.apply)
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        outer.addLayout(buttons)

    def apply(self):
        try:
            values = []
            for part in self.input.text().replace("，", ",").split(","):
                if not part.strip():
                    continue
                a, b = part.split(":")
                offset, mask = int(a.strip(), 0), int(b.strip(), 0)
                p = self.save.profile
                if not p.toggle_flags <= offset < p.event_flags+320 or not 1 <= mask <= 255:
                    raise ValueError("偏移须在当前格式的事件区内，掩码须在 0x01–0xFF。")
                values.append((offset+10 if p.japanese else offset, mask))
            self.bindings = tuple(dict.fromkeys(values))
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc) or "请输入偏移:掩码。")
            return
        self.accept()
