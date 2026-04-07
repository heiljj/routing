"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import itertools
from icestorm.icebox.icebox import iceconfig

icebox = iceconfig()
icebox.setup_empty_5k()

def generate_lookup(tile: tuple[int, int]) -> dict[str, list[str]]:
    nets = icebox.tile_db(*tile)
    nets = filter(lambda x : x[1] in ("buffer", "routing"), nets)
    # src, dst, config
    nets = [(x[2], x[3], tuple(x[0])) for x in nets]
    nets = filter(lambda x: "sp" in x[0] and "sp" in x[1], nets)

    # src -> dst, bitconfig
    return {k: [x[1:] for x in i] for k, i in itertools.groupby(nets, key=lambda x : x[0])}

class NoPathFoundException(Exception): ...

def route(target_tile: tuple[int, int], start_tile: tuple[int, int], src_net: str, disallowed_nets: list[str], disallowed_tiles: list[tuple[int, int]], depth=40) -> list[tuple[int, int, str]]:
    """Route span in start tile to span in target tile using only span to span connections. Ignores disallowed nets and nets crossing into
    disallowed tiles. Returns path of connections as [(x, y, net_name)], where net_name is named relative to the previous entry
    (the first entry is named relative to the starting tile)."""
    internal_lookup = generate_lookup(start_tile)
    search_paths = [[(*start_tile, src_net, None)]]

    visited_locations = set()

    for _ in range(depth):
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
            for buffer, config in internal_lookup.get(net, []):
                if (x, y, buffer, config) in visited_locations:
                    continue

                visited_locations.add((x, y, buffer, config))

                next_paths.append(path + [(x, y, buffer, config)])

        search_paths = next_paths

    raise NoPathFoundException()
