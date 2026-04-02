from __future__ import annotations
from typing import Any, Protocol, Generator, Callable
import random
import re
from enum import Enum, auto
from icestorm.icebox.icebox import iceconfig

icebox = iceconfig()
icebox.setup_empty_5k()
t = 1

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

class BufferOption(ConfigOption):
    # TODO
    src = None
    dst = None

class RoutingOption(ConfigOption):
    # TODO
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

    def write(self, tile: list[str], x, y):
        for setting in self.settings.values():
            setting.write(tile)

        return f".logic {x} {y}\n" + "\n".join(tile)

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
    def valid(self, x, y, option):
        return True

class TSF:
    def build(self):
        return ["0" * 54 for _ in range(16)]

tiles = build_tiles([(18, 30)], CF())
t = tiles[(18, 30)]

rep = ["0" * 54 for _ in range(16)]
print(t.write(rep, 3, 3))

setting = list(t.settings.values())[0]
option = setting.enumerate()[0]

print(option)
t.set(option)
print(t.write(rep, 3, 3))
