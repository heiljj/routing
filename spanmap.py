"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import itertools
import functools
from icestorm.icebox.icebox import iceconfig
from dataclasses import dataclass
from repr import ConfigOption, parse_config_bit
from icestorm.icebox.icebox_asc2hlc import translate_netname
from icestorm.icebox.icebox_hlc2asc import untranslate_netname

icebox = iceconfig()
icebox.setup_empty_5k()

@functools.cache
def generate_lookup(tile: tuple[int, int]) -> dict[str, list[str]]:
    """Creates a lookup table of potential local network connections in a tile."""
    nets = icebox.tile_db(*tile)
    routing_nets = list(filter(lambda x : x[1] == "routing", nets))
    buffer_nets = list(filter(lambda x : x[1] == "buffer", nets))

    nets = list(routing_nets) + buffer_nets
    # src, dst, config
    nets = [(x[2], x[3], tuple(x[0])) for x in nets]
    nets = sorted(nets, key=lambda x : x[0])

    # src -> dst, bitconfig
    return {k: ([x[1:] for x in i]) for k, i in itertools.groupby(nets, key=lambda x : x[0])}

def route(target_tile: tuple[int, int], start_tile: tuple[int, int], src_net: str, disallowed_nets: set[str], depth=100, target_net=None) -> list[tuple[int, int, str]] | None:
    """Route span in start tile to span in target tile using only span to span connections. Ignores disallowed nets and nets crossing into
    disallowed tiles. Returns path of connections as [(x, y, net_name)], where net_name is named relative to the previous entry
    (the first entry is named relative to the starting tile).
    NOTE: disallowed nets can only contain spans and uses the global naming scheme rather than the local one. Local
    span names can be converted using asc2hlc.translate_netname."""
    search_paths = [[(*start_tile, src_net, None)]]

    visited_locations = set(search_paths[0][0])

    for i in range(depth):
        next_paths = []
        for path in search_paths:
            for x, y, net, in icebox.follow_net(path[-1][:3]):

                if (x, y, net, None) in visited_locations:
                    continue

                visited_locations.add((x, y, net, None))

                if target_tile == (x, y) and target_net in [net, None]:
                    return path + [(x, y, net, None)]

                glb_netname = translate_netname(x, y, icebox.max_x, icebox.max_y, net)
                if glb_netname in disallowed_nets:
                    continue

                next_paths.append(path + [(x, y, net, None)])

            x, y, net, _ = path[-1]
            internal_lookup = generate_lookup((x, y))
            for buffer, config in internal_lookup.get(net, []):
                if (x, y, buffer, config) in visited_locations:
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
        new_r_nets = route_io(config.pin, config.output_tile, config.output_net, icebox, disallowed_tiles=config.genome)
        r_nets = r_nets.union(new_r_nets)
        print(r_nets)

    icebox.write_file(file)

    # part of bitstream format
    with open(file, "r+") as f:
        contents = f.read()
        f.write(".comment generated seed file\n" + contents)

def configure(pin: int, target: tuple[int, int], xs: int, ys: int, net=None) -> SeedConfig:
    genome_tiles = {(x, y) for x in range(target[0], target[0] + xs) for y in range(target[1], target[1] + ys)}
    return SeedConfig(pin, target, net, genome_tiles)



# genome_tiles = {(x, y) for x in range(9, 25) for y in range(14, 26)}
# config = SeedConfig(27, (9, 25), None, genome_tiles)
configs = [configure(25, (1, 1), 4, 4),
           configure(21, (16, 16), 4, 4),
           configure(9, (16, 16), 4, 4),
           configure(27, (20, 20), 4, 4)]

configure_seed(configs, "test_seed.asc")

# genome_tiles2 = {(x, y) for x in range(13, 18) for y in range(13, 19)}
# config2 = SeedConfig(25, (13, 18), None, genome_tiles)
# configure_seed([config, config2], "test_seed.asc")