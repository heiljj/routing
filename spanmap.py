from icestorm.icebox.icebox import iceconfig

OUT_FILE = "spanmap.txt"

icebox = iceconfig()
icebox.setup_empty_5k()

def route(target_tile, start_tile, src_net, disallowed_nets, disallowed_tiles, depth=10):
    search_paths = [[(*start_tile, src_net)]]

    for _ in range(depth):
        next_paths = []
        for path in search_paths:
            for x, y, net in icebox.follow_net(path[-1]):
                if (x, y) in disallowed_tiles or net in disallowed_nets:
                    continue

                if (x, y, net) in path:
                    continue

                if target_tile == (x, y):
                    return path + [(x, y, net)]

                next_paths.append(path + [(x, y, net)])


        search_paths = next_paths

    raise Exception()

def find_tiles(src):
    nets = icebox.tile_db(*src)
    nets = filter(lambda x : len(x) == 4, nets)
    nets = filter(lambda x : "out" in x[2], nets)
    nets = filter(lambda x : "sp" in x[3], nets)
    nets = [x[3] for x in nets]

    for x in range(1, 30):
        for y in range(1, 30):
            if src == (x, y):
                continue

            for net in nets:
                try:
                    path = route((x, y), src, net, [], [], depth=10)
                    with open(OUT_FILE, "a") as f:
                        f.write(f"({src[0]}, {src[1]}) -> ({x}, {y})\n")
                    break
                except Exception:
                    pass

    return False

for x in range(1, 30):
    for y in range(1, 30):
        find_tiles((x, y))
