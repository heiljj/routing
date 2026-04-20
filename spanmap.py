"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import itertools
import functools
from icestorm.icebox.icebox import iceconfig
from dataclasses import dataclass
from repr import ConfigOption, parse_config_bit, ConfigBit
from icestorm.icebox.icebox_asc2hlc import translate_netname
from icestorm.icebox.icebox_hlc2asc import untranslate_netname

icebox = iceconfig()
icebox.setup_empty_5k()

@functools.cache
def generate_lookup(tile: tuple[int, int], reverse=False) -> dict[str, list[str]]:
    """Creates a lookup table of potential local network connections in a tile."""
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

    nets = sorted(nets, key=lambda x : x[0])

    # src -> dst, bitconfig
    return {k: ([x[1:] for x in i]) for k, i in itertools.groupby(nets, key=lambda x : x[0])}

# TODO this better
D_TILES = set((x, y) for x in [0, 25] for y in range(1, 31))

def route(target_tile: tuple[int, int], start_tile: tuple[int, int], src_net: str, disallowed_nets: set[str], depth=100, target_net=None, disallowed_tiles: set[tuple[int, int]]=D_TILES) -> list[tuple[int, int, str]] | None:
    """Route span in start tile to span in target tile using only span to span connections. Ignores disallowed nets and nets crossing into
    disallowed tiles. Returns path of connections as [(x, y, net_name)], where net_name is named relative to the previous entry
    (the first entry is named relative to the starting tile).
    NOTE: disallowed nets can only contain spans and uses the global naming scheme rather than the local one. Local
    span names can be converted using asc2hlc.translate_netname."""
    search_paths = [[(*start_tile, src_net, None)]]

    visited_locations = set(search_paths[0][0])

    for i in range(depth):
        print(i)
        next_paths = []
        for path in search_paths:
            for x, y, net, in icebox.follow_net(path[-1][:3]):

                if (x, y, net, None) in visited_locations:
                    continue

                if (x, y) in disallowed_tiles:
                    continue

                visited_locations.add((x, y, net, None))

                if target_tile == (x, y) and target_net in [net, None]:
                    return path + [(x, y, net, None)]

                if target_tile == (x, y):
                    internal_lookup = generate_lookup((x, y), reverse=True)
                    for buffer, config in internal_lookup.get(net, []):
                        if buffer == target_net:
                            return path + [(x, y, net, None), (x, y, buffer, config)]

                glb_netname = translate_netname(x, y, icebox.max_x, icebox.max_y, net)
                if glb_netname in disallowed_nets:
                    continue

                next_paths.append(path + [(x, y, net, None)])

            x, y, net, _ = path[-1]
            internal_lookup = generate_lookup((x, y), reverse=True)
            for buffer, config in internal_lookup.get(net, []):
                if (x, y, buffer, config) in visited_locations:
                    continue

                if (x, y) in disallowed_tiles:
                    continue

                visited_locations.add((x, y, buffer, config))

                next_paths.append(path + [(x, y, buffer, config)])

        search_paths = next_paths
        if not search_paths:
            break

    return None

def get_config_option(tile: tuple[int, int], kind: str, arg: str):
    """Look up config bits based on config option type and first argument."""
    for row in icebox.tile_db(*tile):
        if row[1] == kind:
            if row[2] == arg:
                return row[0]

def write_config_option(tile: tuple[int, int], icebox: iceconfig, bits: list[str]):
    """Writes icestorm formatted bitstring to iceconfig tile."""
    values = [x[0] != "!" for x in bits]
    locations = [parse_config_bit(x) if x[0] != "!" else parse_config_bit(x[1:]) for x in bits]
    ConfigOption(locations, values).write(icebox.tile(*tile))

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

def prepare_io(tile: tuple[int, int], pin_out) -> list[tuple[tuple[str], tuple[str]]]:
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

def route_io(pin: int, dst_tile: tuple[int, int], dst_net: str, icebox: iceconfig, disallowed_tiles: set[tuple[int, int]]=set(), disallowed_nets: dict[tuple[int, int], set[str]]=set()):
    # TODO need to configure pin, change pin out to actual pin
    io_tile, pin_out = configure_io(pin, icebox)
    nets = prepare_io(io_tile, pin_out)

    for io_path, io_conf in nets:
        path = route(dst_tile, io_tile, io_path[0], disallowed_nets, target_net=dst_net)
        if not path:
            continue

        used_nets = set()

        for x, y, net, bits in path:
            if not bits:
                continue
            values = [x[0] != "!" for x in bits]
            locations = [parse_config_bit(x) if x[0] != "!" else parse_config_bit(x[1:]) for x in bits]
            option = ConfigOption(locations, values)
            option.write(icebox.tile(x, y))
            used_nets.add(translate_netname(x, y, icebox.max_x, icebox.max_y, net))

        for bits in io_conf:
            values = [x[0] != "!" for x in bits]
            locations = [parse_config_bit(x) if x[0] != "!" else parse_config_bit(x[1:]) for x in bits]
            option = ConfigOption(locations, values)
            option.write(icebox.tile(*io_tile))


        return used_nets

    raise Exception

@dataclass
class SeedConfig:
    pin: int
    output_tile: tuple[int, int]
    output_net: str | None
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

from repr import Genome, build_tiles, CF, GenomeWriter
# xs = 4
# ys = 29
# target_tiles = [(1, 30), (7, 30), (14, 30), (20, 30)]
# pins = [9, 11, 25, 27]
target_tiles = [(8, 19), (8, 19), (7, 14), (7, 14)]
pins = [9, 11, 25, 27]

writer = GenomeWriter(dict(zip(target_tiles, pins)))

configs = [configure(pin, tile, 7, 10, net="sp4_v_b_0") for pin, tile in zip(pins, target_tiles)]
configure_seed([configs[3]], "test_seed.asc")

all_tiles = [(x, y) for x in range(8, 16) for y in range(19, 25) if (x, y) in icebox.logic_tiles]
built = build_tiles(all_tiles, CF(all_tiles, [(8, 19)]))
starting_genome = Genome(built)

# for i in range(50):
#     genomes = [starting_genome.clone() for _ in range(len(pins))]
#     for genome in genomes:
#         genome.mutate(0.5)

#     writer.write("test_seed.asc", f"out/test_latest_output_{i}.asc", genomes, (8, 19))
