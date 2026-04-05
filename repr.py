from __future__ import annotations
from typing import Any, Protocol, Generator, Callable
import random
import re
from enum import Enum, auto
from icestorm.icebox.icebox import iceconfig


class ConfigType:
    buffer = auto()
    routing = auto()


class ConfigOption:
    def __init__(self, bits: list[str], kind: str, data: list[Any]):
        # id is same for conflicting settings
        self.settings = [b if b[0] != "!" else b[1:] for b in bits]
        self.id = "".join(self.settings)
        self.values = [True if b[0] != "!" else False for b in bits]
        self.values_hash = ",".join(str(i) for i in self.values)
        # buffer, routing
        self.kind = kind
        # extra data such as specific nets for a buffer
        self.data = data

    def conflicts(self, other: ConfigOption):
        return self.id != other.id
# routing options
# CarryInSet
# ColBufCtrl
# LC_(0-7) - this needs to be handled separately

# manually generate ConfigOptions for each bit


# NegClk
# buffer
# routing

class CarryInSet(ConfigOption):
    enable = True

class ColBufCtrl(ConfigOption):
    net_number = 0
    enable = True

class LCLut(ConfigOption):
    cell = 0
    bit = 0
    enable = True

class NegClk(ConfigOption):
    enable = None

class Buffer(ConfigOption):
    src = None
    dst = None

class Routing(ConfigOption):
    net1 = None
    net2 = None

def parse_config_bit(bit: str) -> tuple[int, int]:
    row = re.search(r"B(\d+)", bit).group(1)
    col = re.search(r"\[(\d+)\]", bit).group(1)
    return (int(row), int(col))

class ConfigSetting:
    def __init__(self, options: set[ConfigOption]):
        self.options = {option.values_hash: option for option in options}
        self.current = None

    def numBits(self):
        return len(self.options[0].bits)

    def enumerate(self) -> list[ConfigOption]:
        return list(self.options.values())

    def set(self, option: ConfigOption):
        if option.values_hash not in self.options:
            raise Exception

        self.current = option.values_hash

    def write(self, tile: list[str]):
        if self.current:
            option = self.options[self.current]
            for bit, value in zip(option.settings, option.values):
                row, col = parse_config_bit(bit)

                current = list(tile[row])
                current[col] = "1" if value else "0"
                tile[row] = "".join(current)

    def mutate(self):
        self.current = random.choice(list(self.options.keys()))

class Tile:
    def __init__(self, settings: dict[str, ConfigSetting]):
        self.settings = settings

    def mutate(self, chance):
        for setting in self.settings.values():
            if random.random() < chance:
                setting.mutate()

    def write(self, tile: list[str]):
        for setting in self.settings.values():
            setting.write(tile)

    def set(self, option: ConfigOption):
        self.settings[option.id].set(option)

class ConfigFilter(Protocol):
    def valid(self, x, y, option: ConfigOption):
        pass

class TileSeedFactory(Protocol):
    def build(self) -> list[str]:
        pass

def build_options(iceconfig_settings: list[list[str]]) -> Generator[ConfigOption]:
    for setting in iceconfig_settings:
        bits = setting[0]
        kind = setting[1]
        data = setting[2:]

        yield ConfigOption(bits, kind, data)

# NOTE tile locations are meant to be relative with ConfigFilter
# perfectly fine to create multiple genomes from the same settings and
# write to different tile groups so long as they are the same shape
def build_tile(x: int, y: int, cfilter: ConfigFilter) -> Tile:
    options = build_options(icebox.tile_db(x, y))

    settings: dict[set[ConfigOption]] = {}
    for option in options:
        if not cfilter.valid(x, y, option):
            continue

        if option.id not in settings:
            settings[option.id] = set()

        settings[option.id].add(option)

    return Tile({setting: ConfigSetting(options) for setting, options in settings.items()})

def build_tiles(tiles: list[tuple[int, int]], cfilter: ConfigFilter) -> dict[tuple[int, int], Tile]:
    out = {}

    for x, y in tiles:
        out[(x, y)] = build_tile(x, y, cfilter)

    return out

class CF:
    def __init__(self, valid_tiles: list[tuple[int, int]]):
        self.valid_tiles = valid_tiles

    def valid(self, x, y, option):
        if option.kind == "buffer" or option.kind == "routing":
            src = option.data[0]
            dst = option.data[1]

            if "glb" in src or "glb" in dst:
                return False

            if "sp" in src:
                for x, y, netcon in icebox.follow_net((x, y, src)):
                    if (x, y) not in self.valid_tiles:
                        return False

            if "sp" in dst:
                for x, y, netcon in icebox.follow_net((x, y, dst)):
                    if (x, y) not in self.valid_tiles:
                        return False

            print(option.data)

        return True

class TSF:
    def build(self):
        return ["0" * 54 for _ in range(16)]

icebox = iceconfig()
icebox.setup_empty_5k()
icebox.read_file("out_circuit.asc")

all_tiles = [(x, y) for x in range(15, 20) for y in range(15, 20)]

tiles = build_tiles(all_tiles, CF(all_tiles))
for t in tiles.values():
    t.mutate(0.5)

for x, y in tiles:
    r = icebox.tile(x, y)
    t = tiles[(x, y)]
    t.write(r)

import itertools
icebox.write_file("latest_out_circuit.asc")

# use icebox.follow_net for config parser
# need logic configs

# routing options
# CarryInSet
# ColBufCtrl
# LC_(0-7) - this needs to be handled separately

# manually generate ConfigOptions for each bit


# NegClk
# buffer
# routing

class MutationConfig:
    def __init__(self, tiles: tuple[tuple[int, int]]): ...
    def enableGlobalNets(self): ...
    def enableLogicCell(self, num: int): ...
    def enableLocalSpans(self): ...
    def enableAllSpans(self): ...

class EvolutionConfig:
    def __init__(self, x_size: int, y_size: int, genome_locations: tuple[tuple[int, int]]): ...
    def enableGlobalNets(self): ...
    def enableLogicCell(self, num: int): ...
    def enableLocalSpans(self): ...
    def enableAllSpans(self): ...
