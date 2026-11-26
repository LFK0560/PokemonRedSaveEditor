from collections import defaultdict
from dataclasses import dataclass

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, QSettings, Qt, QTimer
import json
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .events import CATEGORIES, Event, EventIndex
from .flag_editor import BindingEditor, FlagEditor
from .maps import Atlas
from .style import ACCENT, GOLD, RED, label, message


ROLE = Qt.ItemDataRole.UserRole
TARGET_COLORS = {"fixed": "#ad6832", "leader": "#a9322a", "trainer": "#ab642a", "npc": "#527066",
                 "item": "#236657", "hidden": "#725889", "warp": "#1d5e8c", "overview": "#236657"}


@dataclass(frozen=True)
class Marker:
    kind: str
    title: str
    value: object
    x: float
    y: float


class Canvas(QGraphicsView):
    def __init__(self, on_choose, name):
        super().__init__()
        self.setObjectName(name)
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.start_at = None
        self.on_choose = on_choose
        self.tiles = {}
        self.targets = defaultdict(list)

    def clear(self):
        self.targets.clear()
        self.scene().clear()
        self.resetTransform()

    def pixmap(self, image, key):
        if key not in self.tiles:
            self.tiles[key] = QPixmap.fromImage(ImageQt(image))
        return self.tiles[key]

    def add_bitmap(self, image, key, x: float = 0, y: float = 0, z=0):
        item = self.scene().addPixmap(self.pixmap(image, key))
        item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        item.setPos(x, y)
        item.setZValue(z)
        return item

    def add_marker(self, marker, small=False):
        self.targets[marker.x, marker.y].append(marker)
        x, y = marker.x, marker.y
        pen = QPen(QColor(TARGET_COLORS[marker.kind]))
        pen.setCosmetic(True)
        pen.setWidth(2)
        brush = QBrush(QColor(255, 255, 255, 110))
        radius = 3 if small else 7
        if marker.kind in ("warp", "overview"):
            item = self.scene().addRect(x - radius, y - radius, radius * 2, radius * 2, pen, brush)
        else:
            item = self.scene().addEllipse(x - radius, y - radius, radius * 2, radius * 2, pen, brush)
        item.setZValue(3)
        item.setToolTip(" / ".join(m.title for m in self.targets[x, y]))
        item.setData(0, (x, y))

    def fit(self, rect=None):
        if self.scene().items():
            self.fitInView(rect or self.scene().itemsBoundingRect().adjusted(-14, -14, 14, 14),
                           Qt.AspectRatioMode.KeepAspectRatio)
            if self.transform().m11() > 5:
                self.resetTransform()
                self.scale(5, 5)
                self.centerOn((rect or self.scene().itemsBoundingRect()).center())

    def wheelEvent(self, e):
        steps = e.angleDelta().y()
        if steps:
            self.zoom(1.22 ** (steps / 120))
        e.accept()

    def zoom(self, factor):
        scale = self.transform().m11()
        limit = max(0.14, min(7.0, scale * factor))
        self.scale(limit / scale, limit / scale)

    def mousePressEvent(self, e):
        self.start_at = e.position().toPoint() if e.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        point = e.position().toPoint()
        if self.start_at is None or (point - self.start_at).manhattanLength() > 6:
            self.start_at = None
            return
        self.start_at = None
        coordinate = next((obj.data(0) for obj in self.items(point) if obj.data(0)), None)
        if coordinate:
            rows = self.targets[tuple(coordinate)]
            if len(rows) == 1:
                self.on_choose(rows[0])
            else:
                menu = QMenu(self)
                for m in rows:
                    item = menu.addAction(m.title)
                    item.triggered.connect(lambda _, marker=m: self.on_choose(marker))
                menu.exec(self.mapToGlobal(point))


class FloorDialog(QDialog):
    def __init__(self, parent, name, rows, default=None):
        super().__init__(parent)
        self.setWindowTitle(f"选择楼层 · {name}")
        self.setMinimumWidth(320)
        self.selected = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(19, 16, 19, 16)
        outer.addWidget(label(f"选择楼层 · {name}", "section", True))
        self.floors = QListWidget()
        self.floors.setObjectName("floors")
        for id_, text in rows:
            item = QListWidgetItem(text, self.floors)
            item.setData(ROLE, id_)
            if id_ == default:
                self.floors.setCurrentItem(item)
        if self.floors.currentRow() < 0:
            self.floors.setCurrentRow(0)
        self.floors.itemDoubleClicked.connect(lambda _: self.choose())
        outer.addWidget(self.floors)
        go = QPushButton("打开楼层")
        go.setObjectName("openFloor")
        go.setProperty("primary", True)
        go.clicked.connect(self.choose)
        go.setDefault(True)
        outer.addWidget(go)
        self.resize(350, min(420, 110 + len(rows) * 40))

    def choose(self):
        if item := self.floors.currentItem():
            self.selected = item.data(ROLE)
            self.accept()


class MapPage(QWidget):
    def __init__(self, applied):
        super().__init__()
        self.atlas: Atlas | None = None
        self.index: EventIndex | None = None
        self.save = None
        self.applied = applied
        self.area = None
        self.open_event: Event | None = None
        self.travel = []
        self.binding_scope = None
        self.settings = QSettings("OfflineTools", "PokemonRedSaveEditor")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        self.map_note = label("", "muted", True)
        outer.addWidget(self.map_note)
        controls = QHBoxLayout()
        self.overview_tab = QPushButton("城镇地图")
        self.overview_tab.setObjectName("townMap")
        self.overview_tab.clicked.connect(self.show_overview)
        self.detail_tab = QPushButton("详细地图")
        self.detail_tab.setObjectName("detailMap")
        self.detail_tab.clicked.connect(self.show_world)
        self.back_button = QPushButton("返回上层")
        self.back_button.setObjectName("backMap")
        self.back_button.clicked.connect(self.go_back)
        self.floor_button = QPushButton("选择楼层")
        self.floor_button.setObjectName("chooseFloor")
        self.floor_button.clicked.connect(self.choose_current_floor)
        self.locate = QPushButton("存档位置")
        self.locate.setObjectName("saveLocation")
        self.locate.clicked.connect(self.locate_save)
        self.area_combo = QComboBox()
        self.area_combo.setMinimumWidth(185)
        self.area_combo.setObjectName("mapArea")
        self.area_combo.currentIndexChanged.connect(self.select_area)
        controls.addWidget(self.overview_tab)
        controls.addWidget(self.detail_tab)
        controls.addWidget(self.back_button)
        controls.addWidget(self.floor_button)
        controls.addStretch(1)
        controls.addWidget(self.area_combo, 2)
        controls.addWidget(self.locate)
        self.flags_button = QPushButton("事件标记")
        self.flags_button.clicked.connect(self.edit_flags)
        controls.addWidget(self.flags_button)
        outer.addLayout(controls)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        visual = QWidget()
        visual.setObjectName("surface")
        main = QVBoxLayout(visual)
        main.setContentsMargins(13, 10, 13, 10)
        header = QHBoxLayout()
        self.area_title = label("城镇地图", "section")
        header.addWidget(self.area_title, 1)
        for text, name, handler in (("−", "zoomOut", lambda: self.canvas.zoom(0.82)),
                                    ("+", "zoomIn", lambda: self.canvas.zoom(1.22)),
                                    ("适应窗口", "fitMap", self.fit_map)):
            button = QPushButton(text)
            button.setObjectName(name)
            button.clicked.connect(handler)
            header.addWidget(button)
        main.addLayout(header)
        self.stack = QStackedWidget()
        self.overview_canvas = Canvas(self.choose_marker, "overviewCanvas")
        self.world_canvas = Canvas(self.choose_marker, "worldCanvas")
        self.floor_canvas = Canvas(self.choose_marker, "floorCanvas")
        for view in (self.overview_canvas, self.world_canvas, self.floor_canvas):
            self.stack.addWidget(view)
        main.addWidget(self.stack, 1)
        main.addWidget(label("拖动平移 · 滚轮缩放 · 蓝色方框进入门或楼梯 · 圆形标记查看事件", "muted", True))
        split.addWidget(visual)

        detail = QWidget()
        detail.setObjectName("surface")
        detail.setMinimumWidth(285)
        side = QVBoxLayout(detail)
        side.setContentsMargins(14, 11, 14, 12)
        side.addWidget(label("事件目标", "section"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("按名称或对象 ID 搜索全图")
        self.filter.setObjectName("eventFilter")
        self.filter.textChanged.connect(self.update_list)
        side.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setObjectName("eventList")
        self.list.setAlternatingRowColors(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(self.list_pick)
        self.list.itemClicked.connect(self.list_pick)
        side.addWidget(self.list, 1)
        self.target_name = label("点击地图标记或在列表中选择目标。", "section", True)
        self.target_info = label("", "muted", True)
        self.target_state = label("", "pill", True)
        self.target_state.hide()
        self.reason = label("", "muted", True)
        self.reset_button = QPushButton("复位此事件")
        self.reset_button.setObjectName("resetEvent")
        self.reset_button.setProperty("primary", True)
        self.reset_button.clicked.connect(self.reset_event)
        self.reset_button.setEnabled(False)
        self.binding_button = QPushButton("关联标记…")
        self.binding_button.clicked.connect(self.edit_binding)
        for widget in (self.target_name, self.target_info, self.target_state, self.reason, self.reset_button):
            side.addWidget(widget)
        side.addWidget(self.binding_button)
        split.addWidget(detail)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([745, 300])

    @property
    def canvas(self):
        return self.stack.currentWidget()

    def setup(self, atlas, index):
        self.atlas, self.index = atlas, index
        self.base_events = index.by_key.copy()
        self.binding_scope = None
        self.open_event = None
        self.map_note.setText("✓ 地图数据已认证" if atlas.catalog.verified else
                              "未认证 · 地图与事件已开放。格网底图为参考定位图，事件关联可自行调整。" if atlas.reference_areas or not atlas.tables or atlas.tables.tilesets is None else
                              "未认证 · 地图读取自所选 ROM，事件使用可编辑的通用参考关联。")
        self.travel.clear()
        self.area_combo.blockSignals(True)
        self.area_combo.clear()
        self.area_combo.addItem("定位到地图…", None)
        for area in atlas.areas.values():
            self.area_combo.addItem(f"{area.title}  [{area.id:02X}]", area.id)
        self.area_combo.blockSignals(False)
        self.overview_canvas.clear()
        self.overview_canvas.tiles.clear()
        self.world_canvas.clear()
        self.world_canvas.tiles.clear()
        self.floor_canvas.clear()
        self.floor_canvas.tiles.clear()
        view = self.overview_canvas
        view.add_bitmap(atlas.town_map(), "town")
        for p in atlas.overview:
            view.add_marker(Marker("overview", p.name, p, p.x, p.y), small=True)
        self.build_world()
        self.select_event(None)
        self.show_overview()

    def build_world(self):
        view, atlas = self.world_canvas, self.atlas
        for id_, (x, y) in atlas.positions.items():
            view.add_bitmap(atlas.floor_image(id_), id_, x, y)
            self.mark_area(view, id_, x, y)
        view.scene().setSceneRect(view.scene().itemsBoundingRect().adjusted(-320, -320, 320, 320))

    def mark_area(self, canvas, id_, dx, dy):
        atlas = self.atlas
        for warp in atlas.areas[id_].warps:
            if warp.map_id in atlas.areas:
                name = atlas.areas[warp.map_id].title
            elif warp.map_id == 255:
                name = "返回室外"
            else:
                continue
            canvas.add_marker(Marker("warp", name, (id_, warp), dx + warp.x * 16 + 8, dy + warp.y * 16 + 8))
        for e in self.index.by_map[id_]:
            x, y = dx + e.x * 16 + 8, dy + e.y * 16 + 8
            canvas.add_marker(Marker(e.kind, e.name, e, x, y))
            if e.sprite:
                canvas.add_bitmap(atlas.sprite(e.sprite), ("sprite", e.sprite), x - 8, y - 10, 4)

    def show_overview(self):
        if not self.atlas:
            return
        self.select_event(None)
        self.stack.setCurrentWidget(self.overview_canvas)
        self.area = None
        self.travel.clear()
        self.area_title.setText("关都 · 城镇地图")
        self.sync_controls()
        QTimer.singleShot(0, self.fit_map)

    def show_world(self, map_id=None, *, keep_travel=False):
        if not self.atlas:
            return
        if isinstance(map_id, bool):
            map_id = None
        if not keep_travel:
            self.travel.clear()
        if self.open_event and self.open_event.map_id != map_id:
            self.select_event(None)
        self.stack.setCurrentWidget(self.world_canvas)
        self.area = map_id
        self.area_title.setText(self.atlas.areas[map_id].title if map_id is not None else "关都 · 详细地图")
        self.sync_controls()
        if map_id is None:
            self.world_canvas.fit()
        else:
            x, y = self.atlas.positions[map_id]
            a = self.atlas.areas[map_id]
            self.world_canvas.fit(QRectF(x, y, a.w * 32, a.h * 32).adjusted(-65, -65, 65, 65))

    def show_floor(self, id_):
        if id_ not in self.atlas.areas:
            return
        if self.open_event and self.open_event.map_id != id_:
            self.select_event(None)
        if self.area in self.atlas.areas and self.area in self.atlas.positions and not self.travel:
            self.travel.append(self.area)
        self.area = id_
        a = self.atlas.areas[id_]
        v = self.floor_canvas
        self.stack.setCurrentWidget(v)
        v.clear()
        v.add_bitmap(self.atlas.floor_image(id_), id_)
        self.mark_area(v, id_, 0, 0)
        v.scene().setSceneRect(v.scene().itemsBoundingRect().adjusted(-115, -115, 115, 115))
        self.area_title.setText(a.title)
        self.sync_controls()
        v.fit()

    def fit_map(self):
        if self.canvas is self.world_canvas and self.area in self.atlas.positions:
            self.show_world(self.area, keep_travel=True)
        else:
            self.canvas.fit()

    def sync_controls(self):
        inside = self.canvas is self.floor_canvas
        group = self.atlas.areas[self.area].group if inside else None
        self.floor_button.setVisible(bool(group))
        self.back_button.setVisible(inside)
        self.area_combo.blockSignals(True)
        self.area_combo.setCurrentIndex(max(0, self.area_combo.findData(self.area)))
        self.area_combo.blockSignals(False)
        self.update_list()

    def select_area(self):
        id_ = self.area_combo.currentData()
        if id_ is None:
            return
        self.select_event(None)
        if id_ in self.atlas.positions:
            self.show_world(id_)
        else:
            self.travel.clear()
            self.show_floor(id_)

    def choose_marker(self, marker):
        if isinstance(marker.value, Event):
            e = self.index.by_key.get(marker.value.key, marker.value)
            if self.canvas is self.world_canvas:
                self.area = e.map_id
                self.sync_controls()
            self.select_event(e)
            return
        self.select_event(None)
        atlas = self.atlas
        if marker.kind == "overview":
            point = marker.value
            if point.ids[0] in atlas.positions:
                self.show_world(point.ids[0])
            else:
                ids = point.ids
                preferred = next((i for i in ids if atlas.areas[i].floor == "1F"), ids[0])
                if len(ids) > 1 and not atlas.areas[preferred].group:
                    self.pick_floor(point.name, ids, preferred)
                else:
                    anchor = sorted(atlas.exit_links.get(preferred, []))
                    if anchor:
                        self.show_world(anchor[0])
                        bx, by = atlas.positions[anchor[0]]
                        warp = next(w for w in atlas.areas[anchor[0]].warps if w.map_id == preferred)
                        self.canvas.centerOn(bx + warp.x * 16 + 8, by + warp.y * 16 + 8)
                    else:
                        self.enter(preferred)
            return
        source, warp = marker.value
        if warp.map_id == 255:
            self.go_back()
        elif warp.map_id in atlas.positions:
            self.show_world(warp.map_id)
        elif warp.map_id == source:
            destination = atlas.areas[source].warps
            if self.canvas is self.floor_canvas and warp.entrance < len(destination):
                other = destination[warp.entrance]
                self.canvas.centerOn(other.x * 16 + 8, other.y * 16 + 8)
        else:
            pushed = not self.travel or self.travel[-1] != source
            if pushed:
                self.travel.append(source)
            if not self.enter(warp.map_id) and pushed:
                self.travel.pop()

    def enter(self, map_id):
        a = self.atlas.areas[map_id]
        if a.group:
            return self.pick_floor(a.name, self.atlas.groups[a.group], map_id)
        else:
            self.show_floor(map_id)
            return True

    def pick_floor(self, title, ids, current):
        dialog = FloorDialog(self, title, [(n, self.atlas.areas[n].floor or self.atlas.areas[n].title) for n in ids], current)
        if dialog.exec():
            self.show_floor(dialog.selected)
            return True
        return False

    def choose_current_floor(self):
        if self.area in self.atlas.areas:
            self.enter(self.area)

    def go_back(self):
        self.select_event(None)
        if self.travel:
            id_ = self.travel.pop()
            if id_ in self.atlas.positions:
                self.show_world(id_, keep_travel=True)
            else:
                self.show_floor(id_)
        else:
            choices = sorted(self.atlas.exit_links.get(self.area, []))
            self.show_world(choices[0] if choices else None)

    def locate_save(self):
        if self.save:
            self.select_event(None)
            self.travel.clear()
            id_ = self.save.map_id
            if id_ in self.atlas.positions:
                self.show_world(id_)
            else:
                self.show_floor(id_)

    def set_save(self, save):
        self.save = save
        if save and self.index:
            scope = f"eventBindings/{self.atlas.catalog.sha256 or 'reference'}/{save.profile.name}"
            if scope != self.binding_scope:
                self.index.by_key = self.base_events.copy()
                self.index.by_map = {id_: tuple(e for e in self.base_events.values() if e.map_id == id_)
                                     for id_ in self.atlas.areas}
                try:
                    for row in json.loads(self.settings.value(scope, "[]")):
                        key = (row[0], row[1])
                        flags = tuple(tuple(v) for v in row[2])
                        if key in self.index.by_key and all(0x2852 <= a < 0x2B33 and 1 <= b <= 255 for a, b in flags):
                            self.index.set_binding(key, flags)
                except (ValueError, TypeError, IndexError):
                    pass
                self.binding_scope = scope
        self.locate.setEnabled(bool(save))
        self.flags_button.setEnabled(bool(save))
        self.refresh()

    def refresh(self):
        if self.open_event and self.index:
            self.open_event = self.index.by_key.get(self.open_event.key)
        self.update_list()
        self.select_event(self.open_event)

    def update_list(self):
        if not self.index:
            return
        q = self.filter.text().strip().casefold()
        self.list.clear()
        if q:
            pool = [e for e in self.index.by_key.values()
                    if q in f"{e.name} {self.atlas.areas[e.map_id].title} {e.map_id:02X}:{e.id} {CATEGORIES[e.kind]}".casefold()]
        elif self.area in self.index.by_map:
            pool = self.index.by_map[self.area]
        else:
            pool = [e for e in self.index.by_key.values() if e.kind == "fixed" or e.kind == "leader"]
        for e in pool:
            state = e.status(self.save)
            badge = "✓ 已认证" if e.certified_for(self.save) else "未认证"
            name = f"{e.name}  ·  {badge} · {state}"
            if q or self.area is None:
                name = f"{self.atlas.areas[e.map_id].title} / {name}"
            item = QListWidgetItem(name, self.list)
            item.setData(ROLE, e.key)
            item.setToolTip(name)
            if self.open_event == e:
                self.list.setCurrentItem(item)

    def list_pick(self, item):
        key = item.data(ROLE)
        if not key:
            return
        e = self.index.by_key[tuple(key)]
        if self.area != e.map_id or self.canvas is self.overview_canvas:
            if e.map_id in self.atlas.positions:
                self.show_world(e.map_id)
            else:
                self.show_floor(e.map_id)
        self.select_event(e)

    def select_event(self, event):
        self.open_event = event
        self.target_state.setVisible(bool(event))
        self.target_info.setVisible(bool(event))
        self.reason.setVisible(bool(event))
        self.reset_button.setEnabled(bool(event and self.save))
        self.binding_button.setEnabled(bool(event and self.save))
        self.reset_button.setText("复位此事件" if event and event.flags else "设置关联标记")
        if not event:
            self.target_name.setText("点击地图标记或在列表中选择目标。")
            return
        self.target_name.setText(event.name + (" · ✓ 已认证" if event.certified_for(self.save) else " · 未认证"))
        self.target_info.setText(f"{CATEGORIES[event.kind]} · {event.map_id:02X}:{event.id} · ({event.x}, {event.y})")
        state = event.status(self.save)
        self.target_state.setText(state)
        self.target_state.setStyleSheet("color: " + (RED if "无法" in state else GOLD if "待验证" in state else ACCENT))
        reason = ("影响说明：" + event.disabled) if event.disabled else ""
        if not reason:
            if not event.certified_for(self.save):
                reason = "可按当前关联清除标记；也可自行调整关联。此事件在当前版本的触发结果未认证。"
            elif state == "已完成":
                reason = "可清除此目标的独立标记，在原位置重新触发。"
            elif state == "可触发":
                reason = "当前存档已可触发此事件。"
            elif state == "通路已关闭":
                reason = "圣特安努号已经离港，无法回到该目标。"
            elif state == "地图脚本执行中":
                reason = "此处尚有进行中的地图脚本。请在游戏中结束剧情后存档。"
            elif state == "旗标状态不一致":
                reason = "战斗完成与显隐记录不一致，请用游戏确认当前剧情。"
        association = ", ".join(f"0x{self.save.profile.reference_offset(a) if self.save else a:04X}:0x{b:02X}"
                                for a, b in event.flags)
        self.reason.setText(reason + ("\n关联标记：" + association if association else "\n没有独立关联，可自行填写或使用事件标记编辑。"))
        self.reason.setToolTip(event.evidence)

    def reset_event(self):
        event = self.open_event
        if not (event and self.save):
            return
        if not event.flags:
            self.edit_binding()
            return
        try:
            changed = event.reset(self.save)
        except ValueError as exc:
            message(self, "无法复位", exc)
            return
        if changed:
            self.applied(f"复位 {self.atlas.areas[event.map_id].title} · {event.name}")

    def edit_flags(self):
        if not self.save:
            return
        dialog = FlagEditor(self, self.save)
        if dialog.exec() and dialog.changed:
            self.applied("编辑事件标记")
        dialog.deleteLater()

    def edit_binding(self):
        if not self.save or not self.open_event:
            return
        dialog = BindingEditor(self, self.open_event, self.save)
        if dialog.exec():
            self.open_event = self.index.set_binding(self.open_event.key, dialog.bindings)
            rows = [[key[0], key[1], e.flags] for key, e in self.index.by_key.items()
                    if e != self.base_events.get(key)]
            self.settings.setValue(self.binding_scope, json.dumps(rows))
            self.refresh()
        dialog.deleteLater()
