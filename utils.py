from dataclasses import dataclass
from typing import Protocol
import itertools
from icestorm.icebox.icebox import iceconfig
from bit_utils import *

icebox = iceconfig()
icebox.setup_empty_5k()

# TODO set extra bits
class Config(Protocol):
    def write(self): ...

@dataclass
class Buffer:
    bits: str
    src: str
    dst: str
    tile: tuple[int, int]

    def write(self, box: iceconfig):
        for bit in self.bits:
            if bit[0] == "!":
                continue

            tile = box.tile(*self.tile)
            set_bit(tile, bit, 1)

@dataclass
class ExtraBit:
    x: int
    y: int
    z: int

    def write(self, box: iceconfig):
        box.extra_bits.add((self.x, self.y, self.z))

# Only for logic cell 0
@dataclass
class LUT:
    x: int
    y: int
    lout: list[int]

    def write(self, box: iceconfig):
        # from icestorm logic tile docs
        config_order = ["LC_0[4]", "LC_0[14]", "LC_0[15]", "LC_0[5]", "LC_0[6]", "LC_0[16]", "LC_0[17]", "LC_0[7]", "LC_0[3]",
                        "LC_0[13]", "LC_0[12]", "LC_0[2]", "LC_0[1]", "LC_0[11]", "LC_0[10]", "LC_0[0]"]

        bitmap = {
            "LC_0[0]": "B0[36]",
            "LC_0[1]": "B0[37]",
            "LC_0[2]": "B0[38]",
            "LC_0[3]": "B0[39]",
            "LC_0[4]": "B0[40]",
            "LC_0[5]": "B0[41]",
            "LC_0[6]": "B0[42]",
            "LC_0[7]": "B0[43]",
            "LC_0[8]": "B0[44]",
            "LC_0[9]": "B0[45]",
            "LC_0[10]": "B1[36]",
            "LC_0[11]": "B1[37]",
            "LC_0[12]": "B1[38]",
            "LC_0[13]": "B1[39]",
            "LC_0[14]": "B1[40]",
            "LC_0[15]": "B1[41]",
            "LC_0[16]": "B1[42]",
            "LC_0[17]": "B1[43]",
            "LC_0[18]": "B1[44]",
            "LC_0[19]": "B1[45]"
        }

        for value, config in zip(self.lout, config_order):
            location = bitmap[config]
            t = box.tile(self.x, self.y)
            set_bit(t, location, value)

@dataclass
class IO:
    x: int
    y: int
    PIO: int

    def write(self, box: iceconfig):
        # enable pintype 3 and 4 of IOB_(PIO)
        # enable IoCtrl Ren_(unused pio block)

        if self.PIO == 0:
            bits = ["B0[16]", "B1[3]", "B4[16]"]
        else:
            bits = ["B10[16]", "B14[16]", "B6[2]"]

        t = box.tile(self.x, self.y)
        for bit in bits:
            set_bit(t, bit, 1)

class Tile:
    def __init__(self, x, y):
        # net name -> connections
        self.connection_lookup = {}

        # (src, dst) -> buffer
        self.buffer_lookup = {}

        data = icebox.tile_db(x, y)
        filtered = [row for row in data if "buffer" in row]
        buffers = [Buffer(bits, src, dst, (x, y)) for bits, _, src, dst in filtered]

        for buffer in buffers:
            items: set = self.connection_lookup.get(buffer.src, set())
            items.add(buffer.dst)
            self.connection_lookup[buffer.src] = items
            self.buffer_lookup[(buffer.src, buffer.dst)] = buffer

    def _route(self, src, dst, max_depth=5) -> list[str]:
        """bfs of tile connects"""
        queue = [[item] for item in self.connection_lookup[src]]

        for _ in range(max_depth):
            new_queue = []

            for option in queue:
                last_connection = option[-1]
                if last_connection == dst:
                    return option

                for next_path in self.connection_lookup.get(last_connection, []):
                    if next_path not in option:
                        new_queue.append(option + [next_path])

            queue = new_queue

        raise Exception

    def route(self, src, dst, max_dept=5) -> list[Config]:
        path = [src] + self._route(src, dst, max_depth=max_dept)
        out = []
        for i in range(len(path)-1):
            out.append(self.buffer_lookup.get((path[i], path[i+1])))

        return out

# io tile to global net it can drive
# from tiledb.gbufpin
io_to_glb = {
    (19, 0): 0,
    (6, 0): 1,
    (13, 31): 2,
    (13, 0): 3,
    (19, 31): 4,
    (6, 31): 5,
    (12, 0): 6,
    (12, 31): 7
}

glb_to_extra_bits = {
    0: ExtraBit(0, 690, 334),
    1: ExtraBit(0, 691, 334),
    2: ExtraBit(1, 690, 175),
    3: ExtraBit(1, 691, 175),
    4: ExtraBit(1, 690, 174),
    5: ExtraBit(1, 691, 174),
    6: ExtraBit(0, 690, 335),
    7: ExtraBit(0, 691, 335)
}

# pin to (tilex, tiley), pio
# from tiledb.pins
# TODO add rest
pins_io_config = {
    9: ((15, 0), 0),
    11: ((13, 0), 1),
    21: ((18, 0), 1),
    25: ((19, 31), 1)
}

def route_global_driver(tile: tuple[int, int], logic_net) -> list[Config]:
    """Creates routing from logic_net (neigh equivalent for io tile) to global network driver in iotile (fabout)"""
    net = io_to_glb[tile]

    t = Tile(*tile)
    return t.route(logic_net, "fabout", max_dept=4) + [glb_to_extra_bits[net]]

def generate_lut_passthrough(tile: tuple[int, int]) -> list[Config]:
    """Creates a lut config for logic cell 0 that passes through the lutff_0/in_0 input"""
    table = []
    # based on in3/2/1/0 bit config, so every other has in_0 as 1
    for _ in range(8):
        table.extend([0, 1])

    return [LUT(tile[0], tile[1], table)]

def route_global_receiver(pin: int, tile: tuple[int, int], logic_tile: tuple[int, int], glb_net: int) -> list[Config]:
    """Connects the logic tile to the specified global network, which then can be forwarded to the io tile's pin."""
    path = []
    path += Tile(*logic_tile).route(f"glb_netwk_{glb_net}", "lutff_0/in_0")
    path += generate_lut_passthrough(logic_tile)

    #TODO
    match (tile[0] - logic_tile[0], tile[1] - logic_tile[1]):
        case -1, -1:
            direction = "tnr"
        case 0, -1:
            direction = "top"
        case 1, -1:
            direction = "tnl"

        case -1, 0:
            direction = "lft"
        case 1, 0:
            direction = "rgt"

        case -1, 1:
            direction = "bnr"
        case 0, 1:
            direction = "bot"
        case 1, 1:
            direction = "bnl"

    pio = pins_io_config[pin][1]

    path += [IO(*tile, pio)]
    path += Tile(*tile).route(f"logic_op_{direction}_0", f"io_{pio}/D_OUT_0")
    return path

def enable_global_colbufs(box: iceconfig):
    """Sets all ColBufCtrl bits so that the global networks can propagate among tiles."""

    tiles = []
    tiles.extend(box.io_tiles.keys())
    tiles.extend(box.ramb_tiles.keys())
    tiles.extend(box.ramt_tiles.keys())
    tiles.extend(box.logic_tiles.keys())
    tiles.extend(itertools.chain(*(row.keys() for row in box.dsp_tiles)))
    tiles.extend(box.ipcon_tiles.keys())

    for tile in tiles:
        config = box.tile_db(*tile)
        tile_data = box.tile(*tile)

        for option in config:
            if "ColBufCtrl" in option:
                set_bit(tile_data, option[0][0], 1)

def write(configs: list[Config], box: iceconfig, fname: str):
    for option in configs:
        option.write(box)

    box.write_file(fname)
    # this is stupid but i can't find a iceconfig option
    # comment is required as part of bitstream format
    with open(fname, "r") as f:
        contents = f.read()

    contents = ".comment generated for multi evaluation\n" + contents

    with open(fname, "w") as f:
        f.write(contents)

config = route_global_driver((6, 0), "logic_op_tnl_0")
config.extend(route_global_receiver(9, (15, 0), (15, 1), 7))

config.extend(route_global_driver((13, 0), "logic_op_top_0"))
config.extend(route_global_receiver(11, (17, 0), (17, 1), 3))

enable_global_colbufs(icebox)
write(config, icebox, "out_circuit.asc")
