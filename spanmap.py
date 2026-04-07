"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import itertools
import functools
from icestorm.icebox.icebox import iceconfig
from repr import ConfigOption, parse_config_bit

icebox = iceconfig()
icebox.setup_empty_5k()

@functools.cache
def generate_lookup(tile: tuple[int, int]) -> dict[str, list[str]]:
    """Creates a lookup table of potential local network connections in a tile."""
    nets = icebox.tile_db(*tile)
    # bidirectional
    routing_nets = list(filter(lambda x : x[1] == "routing", nets))
    # routing2_nets = [(x[0], x[1], x[3], x[2]) for x in routing_nets]
    buffer_nets = list(filter(lambda x : x[1] == "buffer", nets))

    # nets = list(routing_nets) + buffer_net + routing2_nets
    nets = list(routing_nets) + buffer_nets
    # nets = list(routing_nets) + buffer_nets
    # src, dst, config
    nets = [(x[2], x[3], tuple(x[0])) for x in nets]
    nets = sorted(nets, key=lambda x : x[0])

    # src -> dst, bitconfig
    return {k: ([x[1:] for x in i]) for k, i in itertools.groupby(nets, key=lambda x : x[0])}

def route(target_tile: tuple[int, int], start_tile: tuple[int, int], src_net: str, disallowed_nets: list[str], disallowed_tiles: list[tuple[int, int]], depth=100, target_net=None) -> list[tuple[int, int, str]] | None:
    """Route span in start tile to span in target tile using only span to span connections. Ignores disallowed nets and nets crossing into
    disallowed tiles. Returns path of connections as [(x, y, net_name)], where net_name is named relative to the previous entry
    (the first entry is named relative to the starting tile)."""
    search_paths = [[(*start_tile, src_net, None)]]

    visited_locations = set(search_paths[0][0])

    for i in range(depth):
        print(i)
        next_paths = []
        for path in search_paths:
            for x, y, net, in icebox.follow_net(path[-1][:3]):
                if (x, y) in disallowed_tiles or net in disallowed_nets:
                    continue

                if (x, y, net, None) in visited_locations:
                    continue

                visited_locations.add((x, y, net, None))

                if target_tile == (x, y) and target_net in [net, None]:
                    return path + [(x, y, net, None)]

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

def route_io(io_tile: tuple[int, int], pin_out: str, dst_tile: tuple[int, int], dst_net: str, icebox: iceconfig, disallowed_tiles: set[tuple[int, int]]=set(), disallowed_nets: dict[tuple[int, int], set[str]]=set()):
    nets = prepare_io(io_tile, pin_out)

    for io_path, io_conf in nets:
        path = route(dst_tile, io_tile, io_path[0], disallowed_nets, disallowed_tiles, target_net=dst_net)
        if not path:
            continue

        for x, y, _, bits in path:
            if not bits:
                continue
            values = [x[0] != "!" for x in bits]
            locations = [parse_config_bit(x) if x[0] != "!" else parse_config_bit(x[1:]) for x in bits]
            option = ConfigOption(locations, values)
            option.write(icebox.tile(x, y))

        for bits in io_conf:
            values = [x[0] != "!" for x in bits]
            locations = [parse_config_bit(x) if x[0] != "!" else parse_config_bit(x[1:]) for x in bits]
            option = ConfigOption(locations, values)
            option.write(icebox.tile(*io_tile))

        return

    raise Exception

route_io((12, 31), "io_1/D_OUT_1", (24, 0), "span4_vert_47", icebox)
icebox.write_file("spantest.asc")
