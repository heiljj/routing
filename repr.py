from __future__ import annotations
from typing import Any, Protocol, Generator, Callable
import random
import re
from enum import Enum, auto
from icestorm.icebox.icebox import iceconfig
from dataclasses import dataclass


class ConfigType:
    buffer = auto()
    routing = auto()

@dataclass
class ConfigBit:
    row: int
    col: int

    def __iter__(self):
        return iter((self.row, self.col))

    def __hash__(self):
        return hash((self.row, self.col))

class ConfigOption:
    # def __init__(self, bits: list[str], kind: str, data: list[Any]):
    #     # id is same for conflicting settings
    #     self.settings = [b if b[0] != "!" else b[1:] for b in bits]
    #     self.id = "".join(self.settings)
    #     self.values = [True if b[0] != "!" else False for b in bits]
    #     self.values_hash = ",".join(str(i) for i in self.values)
    #     # buffer, routing
    #     self.kind = kind
    #     # extra data such as specific nets for a buffer
    #     self.data = data
    def __init__(self, bits, values):
        self.bits = bits
        self.values = values

    def write(self, tile: list[str]):
        for bit, state in zip(self.bits, self.values):
            current = list(tile[bit.row])
            current[bit.col] = "1" if state else "0"
            tile[bit.row] = "".join(current)

    @property
    def conflicts(self):
        return hash((*self.bits,))

    def __hash__(self):
        return hash((*self.bits, *self.values))

class CarryInSet(ConfigOption):
    def __init__(self, bit: ConfigBit, enabled: bool):
        super().__init__([bit], [enabled])

    @property
    def enabled(self) -> bool:
        return self.values[0]

class ColBufCtrl(ConfigOption):
    def __init__(self, bit: ConfigBit, enabled: bool):
        super().__init__([bit], [enabled])

    @property
    def enabled(self) -> bool:
        return self.values[0]

class LCLut(ConfigOption):
    def __init__(self, cell: int, index: int, bit: ConfigBit, enabled: bool):
        super().__init__([bit], [enabled])
        self.cell = cell
        self.index = index

    @property
    def enabled(self) -> bool:
        return self.values[0]

class NegClk(ConfigOption):
    def __init__(self, bit: ConfigBit, enabled: bool):
        super().__init__([bit], [enabled])

    @property
    def enabled(self) -> bool:
        return self.values[0]

class Buffer(ConfigOption):
    def __init__(self, bits: tuple[ConfigBit], values: tuple[bool], src_net: str, dst_net: str):
        super().__init__(bits, values)
        self.src_net = src_net
        self.dst_net = dst_net

class Routing(ConfigOption):
    def __init__(self, bits: tuple[ConfigBit], values: tuple[bool], net1: str, net2: str):
        super().__init__(bits, values)
        self.net1 = net1
        self.net2 = net2

def parse_config_bit(bit: str) -> ConfigBit:
    row = re.search(r"B(\d+)", bit).group(1)
    col = re.search(r"\[(\d+)\]", bit).group(1)
    return ConfigBit(int(row), int(col))

class ConfigSetting:
    def __init__(self, options: set[ConfigOption]):
        self.options = options
        self.current = None

    def enumerate(self) -> list[ConfigOption]:
        return list(self.options.values())

    def set(self, option: ConfigOption):
        if option not in self.options:
            raise Exception

        self.current = option

    def write(self, tile: list[str]):
        if self.current:
            self.current.write(tile)

    def mutate(self):
        self.current = random.choice(list(self.options))

    def crossover(self, other: ConfigSetting, chance):
        if random.random() < chance:
            self.current = other

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
        self.settings[option.conflicts].set(option)

    def crossover(self, other: Tile, chance: float):
        for key in self.settings:
            if random.random() < chance:
                self.settings[key].crossover(other.settings[key], chance)

class ConfigFilter(Protocol):
    def valid(self, x, y, option: ConfigOption):
        pass

class TileSeedFactory(Protocol):
    def build(self) -> list[str]:
        pass

def parse_tile_dbrow(row: list) -> list[ConfigOption]:
    bits = row[0]
    kind = row[1]
    args = row[2:]

    parsed_bits = []
    parsed_values = []
    for bit in bits:
        if bit[0] == "!":
            parsed_bits.append(parse_config_bit(bit[1:]))
            parsed_values.append(False)

        else:
            parsed_bits.append(parse_config_bit(bit))
            parsed_values.append(True)

    match kind:
        case "CarryInSet":
            return [CarryInSet(parsed_bits[0], parsed_values[0])]
        case "ColBufCtrl":
            return [ColBufCtrl(parsed_bits[0], parsed_values[0])]
        case "NegClk":
            return [NegClk(parsed_bits[0], parsed_values[0])]
        case "buffer":
            return [Buffer(parsed_bits, parsed_values, args[0], args[1])]
        case "routing":
            return [Routing(parsed_bits, parsed_values, args[0], args[1])]
        case "RamConfig":
            #TODO
            return []
        case "RamCascade":
            #TODO
            return []
        case _:
            index = int(re.search(r"LC_(\d)", kind).group(1))
            if not 0 <= index <= 7:
                raise Exception("Bad index")

            values = []
            for i, bit in enumerate(parsed_bits):
                values.append(LCLut(index, i, bit, True))
                values.append(LCLut(index, i, bit, False))

            return values

def build_options(iceconfig_settings: list[list[str]]) -> Generator[ConfigOption]:
    for setting in iceconfig_settings:
        for option in parse_tile_dbrow(setting):
            yield option

# NOTE tile locations are meant to be relative with ConfigFilter
# perfectly fine to create multiple genomes from the same settings and
# write to different tile groups so long as they are the same shape
def build_tile(x: int, y: int, cfilter: ConfigFilter) -> Tile:
    options = build_options(icebox.tile_db(x, y))

    settings: dict[set[ConfigOption]] = {}
    for option in options:
        if not cfilter.valid(x, y, option):
            continue

        if option.conflicts not in settings:
            settings[option.conflicts] = set()

        settings[option.conflicts].add(option)

    return Tile({setting: ConfigSetting(options) for setting, options in settings.items()})

class Genome:
    def __init__(self, tiles: dict[tuple[int, int], Tile]):
        self.tiles = tiles

    def mutate(self, chance: float):
        for tile in self.tiles.values():
            tile.mutate(chance)

    def crossover(self, other: Genome, chance: float):
        for location in self.tiles.keys():
            self.tiles[location].crossover(other.tiles[location], chance)

    def write(self, icebox: iceconfig, x_offset: int, y_offset: int):
        for x, y in tiles:
            self.tiles[(x, y)].write(icebox.tile(x + x_offset, y + y_offset))

def build_tiles(tiles: list[tuple[int, int]], cfilter: ConfigFilter) -> dict[tuple[int, int], Tile]:
    out = {}

    for x, y in tiles:
        out[(x, y)] = build_tile(x, y, cfilter)

    return out

class CF:
    def __init__(self, valid_tiles: list[tuple[int, int]]):
        self.valid_tiles = valid_tiles

    def valid(self, x, y, option):
        if isinstance(option, Buffer):
            if "glb" in option.src_net or "glb" in option.dst_net:
                return False

            if "sp" in option.src_net and "sp" in option.dst_net:
                return False

            if "sp" in option.src_net:
                for x, y, netcon in icebox.follow_net((x, y, option.src_net)):
                    if (x, y) not in self.valid_tiles:
                        return False

            if "sp" in option.dst_net:
                for x, y, netcon in icebox.follow_net((x, y, option.dst_net)):
                    if (x, y) not in self.valid_tiles:
                        return False

            return True

        elif isinstance(option, Routing):
            # I think this should probably be disabled in most cases?
            # Having this enabled pretty much means that all the spans will
            # be connected I think
            return False

        elif isinstance(option, LCLut):
            return True

        return False

icebox = iceconfig()
icebox.setup_empty_5k()
icebox.read_file("out_circuit.asc")

all_tiles = [(x, y) for x in range(16, 20) for y in range(16, 20)]

tiles = build_tiles(all_tiles, CF(all_tiles))
tiles2 = build_tiles(all_tiles, CF(all_tiles))

genome = Genome(tiles)
genome2 = Genome(tiles2)

genome.mutate(0.5)
genome2.mutate(0.5)
genome.crossover(genome2, 0.5)

genome.write(icebox, -2, 2)
icebox.write_file("latest_out_circuit.asc")
