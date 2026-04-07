"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import itertools
import functools
from icestorm.icebox.icebox import iceconfig

icebox = iceconfig()
icebox.setup_empty_5k()

@functools.cache
def generate_lookup(tile: tuple[int, int]) -> dict[str, list[str]]:
    nets = icebox.tile_db(*tile)
    # bidirectional
    routing_nets = list(filter(lambda x : x[1] == "routing", nets))
    routing2_nets = [(x[0], x[1], x[3], x[2]) for x in routing_nets]
    buffer_nets = list(filter(lambda x : x[1] == "buffer", nets))

    nets = list(routing_nets) + buffer_nets +routing2_nets
    # nets = list(routing_nets) + buffer_nets
    # src, dst, config
    nets = [(x[2], x[3], tuple(x[0])) for x in nets]
    nets = list(filter(lambda x: "sp" in x[0] and "sp" in x[1], nets))
    nets = sorted(nets, key=lambda x : x[0])

    # src -> dst, bitconfig
    return {k: ([x[1:] for x in i]) for k, i in itertools.groupby(nets, key=lambda x : x[0])}

def route(target_tile: tuple[int, int], start_tile: tuple[int, int], src_net: str, disallowed_nets: list[str], disallowed_tiles: list[tuple[int, int]], depth=100) -> list[tuple[int, int, str]] | None:
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

                if target_tile == (x, y):
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


if __name__ == "__main__":
    from repr import ConfigOption, parse_config_bit
    PATH = "spanmap.txt"


    src = (12, 31)
    dst = (24, 0)
    nets = icebox.tile_db(*src)
    routing_nets = list(filter(lambda x : x[1] == "routing", nets))
    routing2_nets = [(x[0], x[1], x[3], x[2]) for x in routing_nets]
    buffer_nets = list(filter(lambda x : x[1] == "buffer", nets))
    nets = list(routing_nets) + buffer_nets + routing2_nets
    # src, dst, config
    nets = filter(lambda x : x[1] in ("buffer", "routing"), nets)
    nets = [(x[2], x[3], tuple(x[0])) for x in nets]
    nets = filter(lambda x: "sp" in x[0] and "local" in x[1], nets)
    nets = list(set([x[0] for x in nets]))


    for net in nets:
        net = "span4_vert_47"
        path = route(dst, src, net, [], [])
        print(path)
        if path:
            for x, y, _, bits in path:
                if not bits:
                    continue
                values = [x[0] != "!" for x in bits]
                locations = [parse_config_bit(x) if x[0] != "!" else parse_config_bit(x[1:]) for x in bits]
                option = ConfigOption(locations, values)
                option.write(icebox.tile(x, y))

        icebox.write_file("spantest.asc")
        print("done!")
        break



