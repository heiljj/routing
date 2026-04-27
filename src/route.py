"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import itertools
import functools
from dataclasses import dataclass
from icebox_asc2hlc import translate_netname
from icebox import iceconfig
from genome import ConfigOption, parse_config_bit, ConfigBit, bits_to_option

IPCONF_TILES = set((x, y) for x in [0, 25] for y in range(1, 31))

icebox = iceconfig()
icebox.setup_empty_5k()


@functools.cache
def generate_lookup(tile: tuple[int, int], reverse=False) -> dict[str, tuple[str, ConfigOption]]:
    """Creates a lookup table of potential forward routing/buffer network connections in a tile.
    Set reverse=True for backwards instead."""
    nets = icebox.tile_db(*tile)
    routing_nets = list(filter(lambda x : x[1] == "routing", nets))
    buffer_nets = list(filter(lambda x : x[1] == "buffer", nets))

    nets = list(routing_nets) + buffer_nets
    # src, dst, config
    # TODO change
    if reverse:
        nets = [(x[3], x[2], tuple(x[0])) for x in nets]
    else:
        nets = [(x[2], x[3], tuple(x[0])) for x in nets]

    for i in range(len(nets)):
        nets[i] = (nets[i][0], nets[i][1], bits_to_option(nets[i][2]))

    nets = sorted(nets, key=lambda x : x[0])

    # src -> dst, bitconfig
    return {k: ([x[1:] for x in i]) for k, i in itertools.groupby(nets, key=lambda x : x[0])}

# TODO might be able to use ipcon tiles, need to confirm
class Router:
    def __init__(self, start_options: list[tuple[int, int, str]], target_net: tuple[int, int, str], disallowed_nets: set[str]=set(), disallowed_tiles: set[tuple[int, int]]=IPCONF_TILES, depth: int=100):
        """
        - start_options: list of (x, y, netname) options for starting net
        - target_net: (x, y, netname) for destination net
        - disallowed_nets: set of global span names to avoid, can be translated from local net with icebox_hlc2asc.translate_netname
        - disallowed_tiles: set of (x, y) tiles to avoid routing through, nets may still intersect with these tiles
        but they will not be completely contained in them (a genome that avoids outside span connections will not be able to connect)
        - depth: depth of search tree
        """
        self.paths = [[(*option, None)] for option in start_options]
        self.target = target_net
        self.disallowed_nets = disallowed_nets
        self.disallowed_tiles = disallowed_tiles
        self.depth = depth
        self.visited_nets = set()

    def _connection_valid(self, x: int, y: int, net: str):
        """Whether a connection fits tile/net constraints"""
        if (x, y) in self.disallowed_tiles or (x, y, net) in self.visited_nets:
            return False

        glb_netname = translate_netname(x, y, icebox.max_x, icebox.max_y, net)

        return glb_netname not in self.disallowed_nets and glb_netname not in self.visited_nets

    def _path_if_valid(self, path, x, y, net, config):
        """Adds path to queue if new connection is valid"""
        if self._connection_valid(x, y, net):
            self.visited_nets.add((x, y, net))
            self.paths.append(path + [(x, y, net, config)])

    def _follow_path(self, path: list[tuple[int, int, str, ConfigOption | None]]):
        """Explores next options for a path, returns whether path is already complete"""
        x, y, net, bits = path[-1]

        if (x, y, net) == self.target:
            return True

        for new_x, new_y, new_net in icebox.follow_net((x, y, net)):
            self._path_if_valid(path, new_x, new_y, new_net, None)

        lookup = generate_lookup((x, y), reverse=True)
        for buffer, config in lookup.get(net, []):
            self._path_if_valid(path, x, y, buffer, config)

        return False

    def route(self) -> list[tuple[int, int, str, ConfigOption | bool]]:
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


# TODO return ConfigOption
def get_config_option(tile: tuple[int, int], kind: str, arg: str):
    """Look up config bits based on config option type and first argument."""
    for row in icebox.tile_db(*tile):
        if row[1] == kind:
            if row[2] == arg:
                return row[0]

# TODO remove
def write_config_option(tile: tuple[int, int], icebox: iceconfig, bits: list[str]):
    """Writes icestorm formatted bitstring to iceconfig tile."""
    bits_to_option(bits).write(icebox.tile(*tile))

def configure_io(io_pin: int, icebox: iceconfig) -> tuple[tuple[int, int], str]:
    """Writes io pad configuration, returns io tile location and out net. Configures following bits:
    - IOB_[pad] PINTYPE_0, 3, and 4
    - cf_bit_35 or 39 depending on pad location
    - REN_[pad] on corresponding ren tile
    """
    pad_lookup = {row[0]: row[1:] for row in icebox.pinloc_db()}
    x, y, pad = pad_lookup[str(io_pin)]

    ie_lookup = {row[:3]: row[3:] for row in icebox.ieren_db()}
    ren_x, ren_y, ren_pad = ie_lookup[(x, y, pad)]

    ren = f"REN_{ren_pad}"
    bits = get_config_option((ren_x, ren_y), "IoCtrl", ren)
    write_config_option((ren_x, ren_y), icebox, bits)

    if pad == 1:
        cf_bit = "cf_bit_39"
    else:
        cf_bit = "cf_bit_35"

    bits = get_config_option((x, y), "IoCtrl", cf_bit)
    write_config_option((x, y), icebox, bits)

    iob = f"IOB_{pad}"
    for option in ["PINTYPE_0", "PINTYPE_3", "PINTYPE_4"]:
        bits = get_config_option((ren_x, ren_y), iob, option)
        write_config_option((ren_x, ren_y), icebox, bits)

    return ((x, y), f"io_{pad}/D_OUT_0")

def prepare_io(tile: tuple[int, int], pin_out) -> list[tuple[tuple[str], ConfigOption]]:
    """Creates possible combinations of span -> local -> dout."""
    paths = []
    lookup = generate_lookup(tile)
    for span in filter(lambda x : "sp" in x, lookup.keys()):

        lcls = lookup[span]

        for lcl, lcl_config in filter(lambda x : "local" in x[0], lcls):
            douts = lookup[lcl]

            for dout, dout_config in douts:
                if pin_out == dout:
                    paths.append(((span, lcl, dout), (lcl_config, dout_config)))

    return paths

def route_io(pin: int, dst_tile: tuple[int, int], dst_net: str, icebox: iceconfig, disallowed_tiles: set[tuple[int, int]]=set(), disallowed_nets: set[str]=set()):
    """Creates a path between pin and the dst_net on the dst_tile, writes to icebox."""
    io_tile, pin_out = configure_io(pin, icebox)
    nets = prepare_io(io_tile, pin_out)

    io_conf_lu = {(*io_tile, k[0], None): v for k, v in nets}
    router = Router([k[:-1] for k in io_conf_lu.keys()], (*dst_tile, dst_net), disallowed_nets=disallowed_nets, disallowed_tiles=disallowed_tiles)
    if not (path := router.route()):
        raise Exception

    for bits in io_conf_lu[path[0]]:
        bits.write(icebox.tile(*io_tile))

    used_nets = set()

    for x, y, net, bits in path:
        if not bits:
            continue
        bits.write(icebox.tile(x, y))
        used_nets.add(translate_netname(x, y, icebox.max_x, icebox.max_y, net))

    return used_nets

@dataclass
class SeedConfig:
    pin: int
    output_tile: tuple[int, int]
    output_net: str
    genome: set[tuple[int, int]]

def configure_seed(configs: list[SeedConfig], file: str):
    r_nets = set()

    icebox = iceconfig()
    icebox.setup_empty_5k()

    for config in configs:
        new_r_nets = route_io(config.pin, config.output_tile, config.output_net, icebox)
        r_nets = r_nets.union(new_r_nets)

        # TODO this better, enables lutff/out -> span connection
        option = ConfigOption([ConfigBit(0, 48)], [True])
        option.write(icebox.tile(*config.output_tile))

    icebox.write_file(file)

    # part of bitstream format
    with open(file, "r") as f:
        contents = f.read()
    with open(file, "w") as f:
        f.write(".comment generated seed file\n" + contents)

def configure(pin: int, target: tuple[int, int], xs: int, ys: int, net=None) -> SeedConfig:
    genome_tiles = {(x, y) for x in range(target[0], target[0] + xs) for y in range(target[1], target[1] + ys)}
    return SeedConfig(pin, target, net, genome_tiles)

# configs = [configure(25, (1, 1), 4, 4),
#            configure(21, (16, 16), 4, 4),
#            configure(9, (16, 16), 4, 4),
#            configure(27, (20, 20), 4, 4)]

# configure_seed(configs, "test_seed.asc")

# genome_tiles2 = {(x, y) for x in range(13, 18) for y in range(13, 19)}
# config2 = SeedConfig(25, (13, 18), None, genome_tiles)
# configure_seed(configs, "test_seed.asc")

from genome import Genome, build_tiles, CF, GenomeWriter
# xs = 4
# ys = 29
target_tiles = [(1, 30), (7, 30), (14, 30), (20, 30)]
# pins = [9, 11, 25, 27]
# target_tiles = [(8, 19), (8, 19), (7, 14), (7, 14)]
pins = [9, 11, 25, 27]

writer = GenomeWriter(dict(zip(target_tiles, pins)))

configs = [configure(pin, tile, 7, 10, net="sp4_v_b_0") for pin, tile in zip(pins, target_tiles)]
configure_seed(configs, "test_seed.asc")

all_tiles = [(x, y) for x in range(8, 16) for y in range(19, 25) if (x, y) in icebox.logic_tiles]
built = build_tiles(all_tiles, CF(all_tiles, [(8, 19)]))
starting_genome = Genome(built)

for i in range(50):
    genomes = [starting_genome.clone() for _ in range(len(pins))]
    for genome in genomes:
        genome.mutate(0.5)

    writer.write("test_seed.asc", f"out/test_latest_output_{i}.asc", genomes, (8, 19))
