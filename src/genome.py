from __future__ import annotations
from typing import Protocol
from collections.abc import Collection, Generator, Iterable, Container
import random
import re
import functools
from dataclasses import dataclass
from icebox import iceconfig
from icebox_asc2hlc import translate_netname as _translate_netname
from icebox_hlc2asc import untranslate_netname as _untranslate_netname

@dataclass(frozen=True, slots=True)
class Tile:
    x: int
    y: int

    def __add__(self, other):
        return Tile(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Tile(self.x - other.x, self.y - other.y)

    def __hash__(self):
        return hash((self.x, self.y))

@dataclass(frozen=True, slots=True)
class ConfigBit:
    row: int
    col: int

    def __iter__(self):
        return iter((self.row, self.col))

    def __hash__(self):
        return hash((self.row, self.col))

def parse_config_bit(bit: str) -> tuple[ConfigBit, bool]:
    row = re.search(r"B(\d+)", bit).group(1)
    col = re.search(r"\[(\d+)\]", bit).group(1)
    return ConfigBit(int(row), int(col)), bit[0] != "!"

class ConfigOption:
    def __init__(self, bits: Iterable[ConfigBit], values: Iterable[ConfigBit]):
        self.bits = tuple(bits)
        self.values = tuple(values)

    def write(self, tile_data: list[str]):
        for bit, state in zip(self.bits, self.values):
            current = list(tile_data[bit.row])
            current[bit.col] = "1" if state else "0"
            tile_data[bit.row] = "".join(current)

    @property
    def conflicts(self):
        return hash((*self.bits,))

    def __hash__(self):
        return hash((*self.bits, *self.values))

class SingleBitOption(ConfigOption):
    def __init__(self, bit: ConfigBit, enabled: bool):
        super().__init__([bit], [enabled])

    @property
    def enabled(self) -> bool:
        return self.values[0]

class CarryInSet(SingleBitOption): ...

class ColBufCtrl(SingleBitOption): ...

class NegClk(SingleBitOption): ...

class LCLut(SingleBitOption):
    def __init__(self, cell: int, index: int, bit: ConfigBit, enabled: bool):
        super().__init__(bit, enabled)
        self.cell = cell
        self.index = index

class NetOption(ConfigOption):
    def __init__(self, bits: Iterable[ConfigBit], values: Iterable[bool], src_net: str, dst_net: str):
        super().__init__(bits, values)
        self.src_net = src_net
        self.dst_net = dst_net

class Buffer(NetOption): ...

class Routing(NetOption): ...
    # NOTE pretty sure this is directional but might not be

@functools.cache
def _parse_tile_dbrow(row: tuple) -> tuple[ConfigOption]:
    bits = row[0]
    kind = row[1]
    args = row[2:]

    parsed = (parse_config_bit(bit) for bit in bits)
    parsed_bits, parsed_values = zip(*parsed)

    match kind:
        case "CarryInSet":
            return (CarryInSet(parsed_bits[0], parsed_values[0]),)
        case "ColBufCtrl":
            return (ColBufCtrl(parsed_bits[0], parsed_values[0]),)
        case "NegClk":
            return (NegClk(parsed_bits[0], parsed_values[0]),)
        case "buffer":
            return (Buffer(parsed_bits, parsed_values, args[0], args[1]),)
        case "routing":
            return (Routing(parsed_bits, parsed_values, args[0], args[1]),)
        case "RamConfig":
            #TODO
            return tuple()
        case "RamCascade":
            #TODO
            return tuple()
        case "Cascade":
            #TODO
            return tuple()
        case "IpConfig":
            #TODO
            return tuple()
        case "IOB_0":
            #TODO
            return tuple()
        case "IOB_1":
            #TODO
            return tuple()
        case "IoCtrl":
            #TODO
            return tuple()
        case "Icegate":
            #TODO
            return tuple()
        case "PLL":
            #TODO
            return tuple()
        case _:
            # This catches different lut options
            # TODO should have separate options for dffenable type things
            index = int(re.search(r"LC_(\d)", kind).group(1))
            if not 0 <= index <= 7:
                raise Exception("Bad index")

            values = []
            for i, bit in enumerate(parsed_bits):
                values.append(LCLut(index, i, bit, True))
                values.append(LCLut(index, i, bit, False))

            return tuple(values)

def parse_tile_dbrow(row: list) -> tuple[ConfigOption]:
    new_row = (tuple(row[0]), *row[1:])
    return _parse_tile_dbrow(new_row)

def build_options(iceconfig_settings: list[list[str]]) -> Generator[ConfigOption]:
    for setting in iceconfig_settings:
        for option in parse_tile_dbrow(setting):
            yield option

# TODO might want to convert this to correct type
# but probably takes too long?
def bits_to_option(bits: list[str]) -> ConfigOption:
    parsed = (parse_config_bit(bit) for bit in bits)
    bits, values = zip(*parsed)
    return ConfigOption(bits, values)

class ConfigSetting:
    def __init__(self, options: set[ConfigOption], current=None):
        self.options = options
        self.current = current

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
            self.current = other.current

    def clone(self) -> ConfigSetting:
        """Shallow copies ConfigOption structure to avoid having to recompute mutation options."""
        return ConfigSetting(self.options, current=self.current)

class IceConfig:
    def __init__(self):
        self.icebox = iceconfig()
        self.icebox.setup_empty_5k()

    # can't cache with self
    _icebox = iceconfig()
    _icebox.setup_empty_5k()

    @classmethod
    @functools.cache
    def _tile_db(cls, tile: Tile):
        data = cls._icebox.tile_db(tile.x, tile.y)
        return list(build_options(data))

    def tile_db(self, tile: Tile) -> list[ConfigOption]:
        return type(self)._tile_db(tile)

    def pinloc_db(self, pin: int) -> tuple[Tile, int]:
        """pin -> tile, io pad"""
        return {row[0]: (Tile(row[1], row[2]), row[3]) for row in self.icebox.pinloc_db()}[str(pin)]

    def ieren_db(self, tile: Tile, io_pad: int) -> tuple[Tile, int]:
        """tile, io pad -> tile, ieren block"""
        return {(Tile(row[0], row[1]), row[2]): (Tile(row[3], row[4]), row[5]) for row in self.icebox.ieren_db()}[(tile, io_pad)]

    @property
    def logic_tiles(self) -> set[Tile]:
        return set(Tile(x, y) for x, y in self.icebox.logic_tiles)

    def tile(self, tile: Tile):
        return self.icebox.tile(tile.x, tile.y)

    def follow_net(self, tile: Tile, net: str) -> list[tuple[Tile, str]]:
        options = self.icebox.follow_net((tile.x, tile.y, net))
        return [(Tile(x, y), net) for x, y, net in options]

    def write_file(self, filename: str):
        self.icebox.write_file(filename)

        # part of bitstream format
        with open(filename, "r") as f:
            contents = f.read()

        with open(filename, "w") as f:
            f.write(".comment generated seed file\n" + contents)

    def read_file(self, filename: str):
        self.icebox.read_file(filename)

def translate_netname(tile: Tile, net: str):
    return _translate_netname(tile.x, tile.y, IceConfig._icebox.max_x, IceConfig._icebox.max_y, net)

def untranslate_netname(tile: Tile, net: str):
    return _untranslate_netname(tile.x, tile.y, IceConfig._icebox.max_x, IceConfig._icebox.max_y, net)

class ConfigFilter(Protocol):
    def valid(self, tile: Tile, option: ConfigOption) -> bool:
        """Whether a ConfigOption should be selectable for mutation."""
class TileConfig:
    def __init__(self, settings: dict[str, ConfigSetting]):
        self.settings = settings

    @classmethod
    def from_cfilter(cls, tile: Tile, cfilter: ConfigFilter, ic: IceConfig) -> TileConfig:
        """Creates a tile from a ConfigFilter rather than ConfigOptions"""
        options = ic.tile_db(tile)

        settings: dict[set[ConfigOption]] = {}
        for option in options:
            if not cfilter.valid(tile, option):
                continue

            if option.conflicts not in settings:
                settings[option.conflicts] = set()

            settings[option.conflicts].add(option)

        return cls({setting: ConfigSetting(options) for setting, options in settings.items()})

    def mutate(self, chance):
        for setting in self.settings.values():
            if random.random() < chance:
                setting.mutate()

    def write(self, tile: list[str]):
        for setting in self.settings.values():
            setting.write(tile)

    def set(self, option: ConfigOption):
        self.settings[option.conflicts].set(option)

    def crossover(self, other: TileConfig, chance: float):
        for key in self.settings:
            if random.random() < chance:
                self.settings[key].crossover(other.settings[key], chance)

    def clone(self) -> TileConfig:
        """Creates a copy to avoid having to recompute mutation options, don't have to worry about duplicated references
        so long as the internals are not messed with."""
        new_settings = {k: v.clone() for k, v in self.settings.items()}
        return TileConfig(new_settings)

class Genome:
    def __init__(self, tiles: dict[tuple[int, int], TileConfig]):
        self.tiles = tiles

    @classmethod
    def from_cfilter(cls, tiles: Collection[Tile], cfilter: ConfigFilter, ic: IceConfig) -> Genome:
        out = {}

        for tile in tiles:
            out[tile] = TileConfig.from_cfilter(tile, cfilter, ic)

        return cls(out)

    def mutate(self, chance: float):
        for tile in self.tiles.values():
            tile.mutate(chance)

    def crossover(self, other: Genome, chance: float):
        for location in self.tiles.keys():
            self.tiles[location].crossover(other.tiles[location], chance)

    def write(self, ic: IceConfig, tile_offset: Tile):
        for tile in self.tiles:
            self.tiles[tile].write(ic.tile(tile + tile_offset))

    def clone(self) -> Genome:
        """Creates new genome out of the existing tile set with shared ConfigOption references."""
        new_tiles = {k: v.clone() for k, v in self.tiles.items()}
        return Genome(new_tiles)

class GenomeWriter:
    def __init__(self, tile_to_pin: dict[Tile, int]):
        self.tile_to_pin = tile_to_pin

    def write(self, seed: str, fpath: str, genomes: Collection[Genome], reference_tile: Tile) -> dict[Genome, int]:
        """Writes genomes to circuit file. Each genome is translated from the starting reference
        tile to one included in the tile_to_pin map. Returns mapping of genome to io pin."""
        ic = IceConfig()
        ic.read_file(seed)
        out = {}
        for genome, target_tile in zip(genomes, self.tile_to_pin.keys()):
            out[genome] = self.tile_to_pin[target_tile]
            genome.write(ic, target_tile - reference_tile)

        ic.write_file(fpath)

offset_map = {
    "tnr": (1, 1),
    "top": (0, 1),
    "tnl": (-1, 1),
    "lft": (-1, 0),
    "rgt": (1, 0),
    "bnr": (1, -1),
    "bot": (0, -1),
    "bnl": (-1, -1)
}

# TODO make this configurable and clean
class CF:
    def __init__(self, valid_tiles: Container[Tile], start_tiles: Collection[Tile] , reference_tile: Tile, ic: IceConfig, avoid_nets: Container[tuple[Tile, str]]=None):
        self.valid_tiles = valid_tiles
        self.pin_tiles = start_tiles
        self.reference_tile = reference_tile
        self.avoid_nets = set()
        self.ic = ic

        for tile, net in avoid_nets:
            tile_delta = self.reference_tile - tile

            for tile in self.pin_tiles:
                try:
                    new_tile = tile + tile_delta

                    if 1 <= new_tile.x <= 24 and 1 <= new_tile.y <= 30:
                        self.avoid_nets.add(translate_netname(new_tile, net))
                except Exception:
                    print(f"Failed glb net translate: {tile, net} to {new_tile, net}")

    def valid(self, tile, option):
        if isinstance(option, Buffer):
            if "glb" in option.src_net or "glb" in option.dst_net:
                return False

            if "sp" in option.src_net and "sp" in option.dst_net:
                return False

            # TODO prevent ice40viewer issues, this is an important connection so remove at some point
            if "lout" in option.src_net:
                return False

            nets = []

            if "sp" in option.src_net:
                nets.append((tile, option.src_net))

            if "sp" in option.dst_net:
                nets.append((tile, option.dst_net))

            if "neigh" in option.src_net or "logic" in option.src_net:
                direction = re.search(r"op_(.*)_\d", option.src_net).group(1)

                offset = offset_map[direction]
                if (tile.x + offset[0], tile.y + offset[1]) not in self.valid_tiles:
                    return False

            for net in nets:
                if "sp" in net:
                    glb_name = translate_netname(tile, net)
                    if glb_name in self.avoid_nets:
                        return False

                if "s_r" in net:
                    return False

            if option.dst_net == "local_g0_0" and tile in self.pin_tiles:
                return False

            found = set(nets)

            while nets:
                tile, name = nets.pop()
                new_nets = self.ic.follow_net(tile, name)

                for net in new_nets:
                    tile = net[0]
                    net = net[1]

                    if tile not in self.valid_tiles:
                        return False

                    if (tile, net) not in found:
                        nets.append((tile, net))
                        found.add((tile, net))

            return True

        elif isinstance(option, Routing):
            # I think this should probably be disabled in most cases?
            # Having this enabled pretty much means that all the spans will
            # be connected I think
            return False

        elif isinstance(option, LCLut):
            return True

        return False

# def create_population(reference_tile: tuple[int, int], x_size: int, y_size: int, amount: int) -> list[Genome]:
#     locations = [(x, y) for x in range(reference_tile[0], reference_tile[0] + x_size) for y in range(reference_tile[1], reference_tile[1] + y_size) if (x, y) in icebox.logic_tiles]
#     tiles = build_tiles(locations, CF(locations, [reference_tile]))
#     genome = Genome(tiles)
#     return [genome.clone() for _ in range(amount)]
