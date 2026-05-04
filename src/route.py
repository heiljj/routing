"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import functools
from dataclasses import dataclass
from icebox_asc2hlc import translate_netname
from icebox import iceconfig
from genome import ConfigOption, ConfigBit, bits_to_option, TileOption, NetOption, parse_tile_dbrow, Tile

IPCONF_TILES = set(Tile(x, y) for x in [0, 25] for y in range(1, 31))

icebox = iceconfig()
icebox.setup_empty_5k()


@functools.cache
def generate_lookup(tile: Tile, reverse=False) -> dict[str, NetOption]:
    """Creates a lookup table of potential forward routing/buffer network connections in a tile.
    Set reverse=True for backwards instead."""

    out = {}
    for row in icebox.tile_db(tile.x, tile.y):
        # list not hashable
        option = parse_tile_dbrow(row)

        if not option:
            continue

        # only LUT options return multiples
        option = option[0]

        if not isinstance(option, NetOption):
            continue

        if not reverse:
            k = option.src_net
            v = option.dst_net
        else:
            k = option.dst_net
            v = option.src_net

        entry = out.setdefault(k, {})
        entry[v] = option

    return out


# TODO might be able to use ipcon tiles, need to confirm
class Router:
    def __init__(self, start_options: list[tuple[Tile, str]], target_net: tuple[Tile, str], disallowed_nets: set[str]=set(), disallowed_tiles: set[Tile]=IPCONF_TILES, depth: int=100):
        """
        - start_options: list of (x, y, netname) options for starting net
        - target_net: (x, y, netname) for destination net
        - disallowed_nets: set of global span names to avoid, can be translated from local net with icebox_hlc2asc.translate_netname
        - disallowed_tiles: set of (x, y) tiles to avoid routing through, nets may still intersect with these tiles
        but they will not be completely contained in them (a genome that avoids outside span connections will not be able to connect)
        - depth: depth of search tree
        """
        self.paths: list[tuple[Tile, str, TileOption | None]] = [[(*option, None)] for option in start_options]
        self.target = target_net
        self.disallowed_nets = disallowed_nets
        self.disallowed_tiles = disallowed_tiles
        self.depth = depth
        self.visited_nets: set[tuple[Tile, str]] = set()

    def _connection_valid(self, tile: Tile, net: str):
        """Whether a connection fits tile/net constraints"""
        if tile in self.disallowed_tiles or (tile, net) in self.visited_nets:
            return False

        glb_netname = translate_netname(tile.x, tile.y, icebox.max_x, icebox.max_y, net)

        return glb_netname not in self.disallowed_nets and glb_netname not in self.visited_nets

    def _path_if_valid(self, path, tile: Tile, net: str, config: TileOption):
        """Adds path to queue if new connection is valid"""
        if self._connection_valid(tile, net):
            self.visited_nets.add((tile, net))
            self.paths.append(path + [(tile, net, config)])

    def _follow_path(self, path: list[tuple[Tile, str, ConfigOption | None]]):
        """Explores next options for a path, returns whether path is already complete"""
        tile, net, bits = path[-1]

        if (tile, net) == self.target:
            return True

        for new_x, new_y, new_net in icebox.follow_net((tile.x, tile.y, net)):
            self._path_if_valid(path, Tile(new_x, new_y), new_net, None)

        lookup = generate_lookup(tile, reverse=True)
        for buffer, config in lookup.get(net, {}).items():
            self._path_if_valid(path, tile, buffer, config)

        return False

    def route(self) -> list[tuple[Tile, str, ConfigOption | bool]]:
        """Returns list of (x, y, netname, config bits)"""
        for i in range(self.depth):
            if not self.paths:
                break
            print(f"depth: {i}, paths: {len(self.paths)}")
            old_paths = self.paths
            self.paths = []

            while old_paths:
                path = old_paths.pop()
                if self._follow_path(path):
                    return path

        return False


def get_config_option(tile: Tile, kind: str, arg: str) -> ConfigOption:
    """Look up config bits based on config option type and first argument."""
    for row in icebox.tile_db(tile.x, tile.y):
        if row[1] == kind:
            if row[2] == arg:
                return bits_to_option(row[0])

def configure_io(io_pin: int, ic: iceconfig) -> tuple[tuple[int, int], str]:
    """Writes io pad configuration, returns io tile location and out net. Configures following bits:
    - IOB_[pad] PINTYPE_0, 3, and 4
    - cf_bit_35 or 39 depending on pad location
    - REN_[pad] on corresponding ren tile
    """
    pad_lookup = {row[0]: row[1:] for row in ic.pinloc_db()}
    x, y, pad = pad_lookup[str(io_pin)]

    ie_lookup = {row[:3]: row[3:] for row in ic.ieren_db()}
    ren_x, ren_y, ren_pad = ie_lookup[(x, y, pad)]

    ren = f"REN_{ren_pad}"
    bits = get_config_option(Tile(ren_x, ren_y), "IoCtrl", ren)
    bits.write(ic.tile(ren_x, ren_y))

    if pad == 1:
        cf_bit = "cf_bit_39"
    else:
        cf_bit = "cf_bit_35"

    bits = get_config_option(Tile(x, y), "IoCtrl", cf_bit)
    bits.write(ic.tile(x, y))

    iob = f"IOB_{pad}"
    for option in ["PINTYPE_0", "PINTYPE_3", "PINTYPE_4"]:
        bits = get_config_option(Tile(ren_x, ren_y), iob, option)
        bits.write(ic.tile(ren_x, ren_y))

    return (Tile(x, y), f"io_{pad}/D_OUT_0")

def prepare_io(tile: tuple[int, int], pin_out) -> list[tuple[tuple[str], ConfigOption]]:
    """Creates possible combinations of span -> local -> dout."""
    paths = []
    lookup = generate_lookup(tile)
    for span in filter(lambda x : "sp" in x, lookup.keys()):

        lcls = lookup[span]

        for lcl, lcl_config in filter(lambda x : "local" in x[0], lcls.items()):
            douts = lookup[lcl]

            for dout, dout_config in douts.items():
                if pin_out == dout:
                    paths.append(((span, lcl, dout), (lcl_config, dout_config)))

    return paths

# def route_io(pin: int, dst_tile: tuple[int, int], dst_net: str, icebox: iceconfig, disallowed_tiles: set[tuple[int, int]]=set(), disallowed_nets: set[str]=set()):
def route_io(pin: int, dst_tile: Tile, dst_net: str, icebox: iceconfig, disallowed_nets: set[str]=set()):
    """Creates a path between pin and the dst_net on the dst_tile, writes to icebox."""
    io_tile, pin_out = configure_io(pin, icebox)
    nets = prepare_io(io_tile, pin_out)

    io_conf_lu = {(io_tile, k[0], None): v for k, v in nets}
    router = Router([k[:-1] for k in io_conf_lu.keys()], (dst_tile, dst_net), disallowed_nets=disallowed_nets)
    if not (path := router.route()):
        raise Exception

    for bits in io_conf_lu[path[0]]:
        bits.write(icebox.tile(io_tile.x, io_tile.y))

    used_nets = set()
    used_nets_raw = set()

    for tile, net, bits in path:
        if not bits:
            continue
        bits.write(icebox.tile(tile.x, tile.y))
        used_nets_raw.add((tile.x, tile.y, net))
        used_nets.add(translate_netname(tile.x, tile.y, icebox.max_x, icebox.max_y, net))

    return used_nets_raw, used_nets

@dataclass
class SeedConfig:
    pin: int
    output_tile: Tile
    output_net: str
    genome: set[Tile]

def configure_seed(configs: list[SeedConfig], file: str):
    r_nets = set()
    r_nets_raw = set()

    icebox = iceconfig()
    icebox.setup_empty_5k()

    for config in configs:
        bad_tiles = set()
        for cf2 in configs:
            if cf2 is not config:
                bad_tiles |= cf2.genome

        new_r_nets_raw, new_r_nets = route_io(config.pin, config.output_tile, config.output_net, icebox)
        r_nets = r_nets.union(new_r_nets)
        r_nets_raw = r_nets_raw.union(new_r_nets_raw)

        # TODO this better, enables lutff/out -> span connection
        option = ConfigOption([ConfigBit(0, 48)], [True])
        option.write(icebox.tile(config.output_tile.x, config.output_tile.y))

    icebox.write_file(file)

    # part of bitstream format
    with open(file, "r") as f:
        contents = f.read()
    with open(file, "w") as f:
        f.write(".comment generated seed file\n" + contents)

    return r_nets_raw

def configure(pin: int, target: tuple[int, int], xs: int, ys: int, net=None) -> SeedConfig:
    genome_tiles = {(x, y) for x in range(target.x, target.x + xs) for y in range(target.y, target.y + ys)}
    return SeedConfig(pin, target, net, genome_tiles)

# configs = [configure(25, (1, 1), 4, 4),
#            configure(21, (16, 16), 4, 4),
#            configure(9, (16, 16), 4, 4),
#            configure(27, (20, 20), 4, 4)]

# configure_seed(configs, "test_seed.asc")

# genome_tiles2 = {(x, y) for x in range(13, 18) for y in range(13, 19)}
# config2 = SeedConfig(25, (13, 18), None, genome_tiles)
# configure_seed(configs, "test_seed.asc")

from genome import Genome, CF, GenomeWriter, Tile
# tiles that output will be located on, going from lutff_0/out -> outgoing span
target_tiles = [Tile(1, 26), Tile(7, 26), Tile(14, 26), Tile(20, 26)]
# pin io numbers
pins = [9, 11, 25, 27]

writer = GenomeWriter(dict(zip(target_tiles, pins)))

# x size 7, y size 20 of genome, sp4_v_b_0 used as outgoing span
configs = [configure(pin, tile, 7, 20, net="sp4_v_b_0") for pin, tile in zip(pins, target_tiles)]
used_nets = configure_seed(configs, "test_seed.asc")

# tile group used to create mutation options, other genome locations need to be identical
# this should be based off of one of the target tiles and have the same size used in configure
all_tiles = [Tile(x, y) for x in range(1, 5) for y in range(6, 27) if (x, y) in icebox.logic_tiles]
starting_genome = Genome.from_cfilter(all_tiles, CF(all_tiles, target_tiles, target_tiles[0], avoid_nets=used_nets))

for i in range(20):
    genomes = [starting_genome.clone() for _ in range(len(pins))]
    for genome in genomes:
        genome.mutate(0.2)

    writer.write("test_seed.asc", f"out/test_latest_output_{i}.asc", genomes, Tile(1, 26))
