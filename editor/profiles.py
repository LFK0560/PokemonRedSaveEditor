"""The two retail Generation I SRAM layouts (all offsets are file offsets)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SaveProfile:
    name: str
    japanese: bool
    name_bytes: int
    party: int
    active_box: int
    main_sum: int
    bag: int
    pc_items: int
    player_id: int
    current_map: int
    box_number: int
    box_count: int
    box_capacity: int
    event_flags: int
    toggle_flags: int
    hidden_flags: int
    event_work: int

    @property
    def box_size(self):
        return (34 + 2 * self.name_bytes) * self.box_capacity + 2

    @property
    def boxes_per_bank(self):
        return self.box_count // 2

    def reference_offset(self, offset):
        # Map scripts, object visibility and hidden-item bits are in this
        # portion of the main data. Japanese names remove ten preceding bytes.
        return offset - 10 if self.japanese and 0x2601 <= offset < 0x2CED else offset


INTERNATIONAL = SaveProfile(
    "国际版", False, 11, 0x2F2C, 0x30C0, 0x3523, 0x25C9, 0x27E6,
    0x2605, 0x260A, 0x284C, 12, 20, 0x29F3, 0x2852, 0x299C, 0x289C,
)
JAPANESE = SaveProfile(
    "日版", True, 6, 0x2ED5, 0x302D, 0x3594, 0x25C4, 0x27DC,
    0x25FB, 0x2600, 0x2842, 8, 30, 0x29E9, 0x2848, 0x2992, 0x2892,
)


def detect_profile(data, preferred=None):
    if len(data) == 0x8000:
        matches = [p for p in (INTERNATIONAL, JAPANESE)
                   if data[p.main_sum] == (~sum(data[0x2598:p.main_sum]) & 255)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            shaped = []
            # A rare checksum collision can usually be resolved by list shapes.
            for p in matches:
                n = data[p.party]
                if (0 < data[0x2598] != 0x50 and 0x50 in data[0x2598:0x2598+p.name_bytes]
                        and n <= 6 and data[p.party + 1 + n] == 255
                        and (data[p.box_number] & 127) < p.box_count):
                    valid = True
                    for start, capacity, stride in ((p.bag, 20, 2), (p.pc_items, 50, 2), (p.active_box, p.box_capacity, 1)):
                        count = data[start]
                        valid &= count <= capacity and data[start+1+count*stride] == 255
                    if valid:
                        shaped.append(p)
            if len(shaped) == 1:
                return shaped[0]
            if preferred in (shaped or matches):
                return preferred
            return (shaped or matches)[0]
    return preferred or INTERNATIONAL
