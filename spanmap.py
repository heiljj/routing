"""Generates list of tiles that can be connected to each other using only direct span to span connections.
The initial network starts from a logic cell output."""
import itertools
from icestorm.icebox.icebox import iceconfig

OUT_FILE = "spanmap.txt"

icebox = iceconfig()
icebox.setup_empty_5k()


# follow_net only works on external nets
nets = icebox.tile_db(15, 15)
nets = filter(lambda x : x[1] in ("buffer", "routing"), nets)
# src, dst
nets = [(x[2], x[3]) for x in nets]
nets = filter(lambda x: all("sp" in y for y in x), nets)

# src -> dst's
internal_lookup = {k: [x[1] for x in i] for k, i in itertools.groupby(nets, key=lambda x : x[0])}

def route(target_tile: tuple[int, int], start_tile: tuple[int, int], src_net: str, disallowed_nets: list[str], disallowed_tiles: list[tuple[int, int]], depth=10) -> list[tuple[int, int, str]]:
    """Route span in start tile to span in target tile using only span to span connections. Ignores disallowed nets and nets crossing into
    disallowed tiles. Returns path of connections as [(x, y, net_name)], where net_name is named relative to the previous entry
    (the first entry is named relative to the starting tile)."""
    search_paths = [[(*start_tile, src_net)]]

    visited_locations = set()

    for _ in range(depth):
        next_paths = []
        for path in search_paths:
            for x, y, net in icebox.follow_net(path[-1]):
                if (x, y) in disallowed_tiles or net in disallowed_nets:
                    continue

                if (x, y, net) in visited_locations:
                    continue

                visited_locations.add((x, y, net))

                if target_tile == (x, y):
                    return path + [(x, y, net)]

                next_paths.append(path + [(x, y, net)])

            x, y, net = path[-1]
            for buffer in internal_lookup.get(net, []):
                if (x, y, buffer) in visited_locations:
                    continue

                visited_locations.add((x, y, buffer))

                next_paths.append(path + [(x, y, buffer)])

        search_paths = next_paths

    raise IndentationError()

def find_tiles(src):
    nets = icebox.tile_db(*src)
    nets = filter(lambda x : len(x) == 4, nets)
    nets = filter(lambda x : "out" in x[2], nets)
    nets = filter(lambda x : "sp" in x[3], nets)
    nets = [x[3] for x in nets]

    for x in range(1, 25):
        for y in range(1, 31):
            if src == (x, y):
                continue

            for net in nets:
                try:
                    path = route((x, y), src, net, [], [], depth=50)
                    with open(OUT_FILE, "a") as f:
                        f.write(f"({src[0]}, {src[1]}) -> ({x}, {y}) (len {len(path)})\n")
                    break
                except IndentationError:
                    pass

    return False

find_tiles((15, 15))
