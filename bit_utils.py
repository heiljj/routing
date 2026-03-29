#!/usr/bin/env python3
"""
Utility functions for reading and writing configuration bits in iceconfig tiles.

Bit strings are formatted as "B<bank>[<bitpos>]", e.g., "B1[49]"
Where:
- B: literal character indicating "Bank"
- <bank>: bank index 0-15 (there are 16 banks per tile)
- <bitpos>: bit position within the bank string (0-53 depending on device)

Tile data is stored as a list of 16 strings, where each string contains '0' or '1'
characters representing the bit values in that bank.
"""

import re
from typing import List, Tuple, Optional


def parse_bit_string(bit_str: str) -> Tuple[int, int]:
    """
    Parse a bit string like "B1[49]" into (bank, bitpos).

    Args:
        bit_str: String in format "B<bank>[<bitpos>]"

    Returns:
        Tuple of (bank_index, bit_position)

    Raises:
        ValueError: If bit_str is not in valid format
    """
    match = re.match(r'B(\d+)\[(\d+)\]', bit_str)
    if not match:
        raise ValueError(f"Invalid bit string format: {bit_str}")

    bank = int(match.group(1))
    bitpos = int(match.group(2))

    if not (0 <= bank <= 15):
        raise ValueError(f"Bank index out of range: {bank}")
    if bitpos < 0:
        raise ValueError(f"Bit position must be non-negative: {bitpos}")

    return bank, bitpos


def get_bit(tile: List[str], bit_str: str) -> int:
    """
    Read a single bit from a tile.

    Args:
        tile: List of 16 bank strings from iceconfig.tile(x, y)
        bit_str: Bit string like "B1[49]"

    Returns:
        0 or 1

    Raises:
        IndexError: If bit position is out of range for the bank
    """
    bank, bitpos = parse_bit_string(bit_str)

    if bitpos >= len(tile[bank]):
        raise IndexError(f"Bit position {bitpos} out of range for bank {bank} "
                        f"(length: {len(tile[bank])})")

    return int(tile[bank][bitpos])


def set_bit(tile: List[str], bit_str: str, value: int) -> None:
    """
    Set a single bit in a tile (modifies tile in-place).

    Args:
        tile: List of 16 bank strings from iceconfig.tile(x, y)
        bit_str: Bit string like "B1[49]"
        value: 0 or 1

    Raises:
        IndexError: If bit position is out of range for the bank
        ValueError: If value is not 0 or 1
    """
    if value not in (0, 1):
        raise ValueError(f"Bit value must be 0 or 1, got: {value}")

    bank, bitpos = parse_bit_string(bit_str)

    if bitpos >= len(tile[bank]):
        raise IndexError(f"Bit position {bitpos} out of range for bank {bank} "
                        f"(length: {len(tile[bank])})")

    # Convert to list, modify, convert back (strings are immutable)
    bank_bits = list(tile[bank])
    bank_bits[bitpos] = str(value)
    tile[bank] = ''.join(bank_bits)


def set_bits(tile: List[str], bit_strings: List[str], value: int = 1) -> None:
    """
    Set multiple bits in a tile to the same value.

    Args:
        tile: List of 16 bank strings
        bit_strings: List of bit strings like ["B1[49]", "B1[50]"]
        value: Value to set (0 or 1, default 1)
    """
    for bit_str in bit_strings:
        set_bit(tile, bit_str, value)


def write_edge_config_to_tile(ic, x: int, y: int,
                              source_net: str, target_net: str) -> bool:
    """
    Write configuration bits to enable a routing edge in a tile.

    This searches the tile database for a matching routing entry and sets
    all required bits to enable that connection.

    Args:
        ic: iceconfig instance
        x, y: Tile coordinates
        source_net: Source net name
        target_net: Target net name

    Returns:
        True if bits were written, False if connection not found
    """
    tile = ic.tile(x, y)
    if tile is None:
        return False

    tile_db = ic.tile_db(x, y)
    if not tile_db:
        return False

    # Find matching routing entry
    for entry in tile_db:
        if len(entry) < 4:
            continue

        if entry[1] not in ("routing", "buffer"):
            continue

        entry_source = entry[2]
        entry_target = entry[3]

        if entry_source == source_net and entry_target == target_net:
            # Found it! Set the bits
            bit_strings = entry[0]
            set_bits(tile, bit_strings, value=1)
            return True

    return False


def clear_edge_config_from_tile(ic, x: int, y: int,
                                source_net: str, target_net: str) -> bool:
    """
    Clear configuration bits to disable a routing edge in a tile.

    Args:
        ic: iceconfig instance
        x, y: Tile coordinates
        source_net: Source net name
        target_net: Target net name

    Returns:
        True if bits were cleared, False if connection not found
    """
    tile = ic.tile(x, y)
    if tile is None:
        return False

    tile_db = ic.tile_db(x, y)
    if not tile_db:
        return False

    # Find matching routing entry
    for entry in tile_db:
        if len(entry) < 4:
            continue

        if entry[1] not in ("routing", "buffer"):
            continue

        entry_source = entry[2]
        entry_target = entry[3]

        if entry_source == source_net and entry_target == target_net:
            # Found it! Clear the bits
            bit_strings = entry[0]
            set_bits(tile, bit_strings, value=0)
            return True

    return False


def print_tile_bits(tile: List[str], highlight_bits: List[str] = None) -> None:
    """
    Pretty-print tile bit information.

    Args:
        tile: List of 16 bank strings
        highlight_bits: Optional list of bit strings to highlight
    """
    highlight_set = set(highlight_bits) if highlight_bits else set()

    print("Tile Bits:")
    print("=" * 70)

    for bank_idx, bank_bits in enumerate(tile):
        # Find which bits are set
        set_bits = []
        for bit_idx, bit in enumerate(bank_bits):
            if bit == '1':
                bit_str = f"B{bank_idx}[{bit_idx}]"
                marker = " <--" if bit_str in highlight_set else ""
                set_bits.append(f"B{bank_idx}[{bit_idx}]{marker}")

        if set_bits:
            print(f"Bank {bank_idx}: {', '.join(set_bits)}")

    print()


# Example usage
if __name__ == "__main__":
    from icestorm.icebox import icebox

    # Create a test configuration
    ic = icebox.iceconfig()
    ic.setup_empty_1k()

    print("Example 1: Reading and writing individual bits")
    print("=" * 70)

    tile = ic.tile(5, 5)
    print(f"Tile at (5, 5) has {len(tile)} banks")

    # Read a bit
    val = get_bit(tile, "B1[10]")
    print(f"Bit B1[10] = {val}")

    # Set a bit
    set_bit(tile, "B1[10]", 1)
    val = get_bit(tile, "B1[10]")
    print(f"After setting, B1[10] = {val}")

    # Clear the bit
    set_bit(tile, "B1[10]", 0)
    val = get_bit(tile, "B1[10]")
    print(f"After clearing, B1[10] = {val}")

    print()
    print("Example 2: Setting multiple bits")
    print("=" * 70)

    # Set multiple bits
    bits_to_set = ["B0[5]", "B0[15]", "B1[20]"]
    set_bits(tile, bits_to_set, value=1)
    print(f"Set bits: {bits_to_set}")
    print_tile_bits(tile, highlight_bits=bits_to_set)

    print()
    print("Example 3: Writing routing configuration")
    print("=" * 70)

    # Try to enable a routing connection
    success = write_edge_config_to_tile(ic, 5, 5, "sp4_h_l_0", "local_in")
    print(f"Write routing config: {'Success' if success else 'Failed'}")

    # Note: The actual nets depend on the tile type and device
    # For a logic tile at (5, 5), try:
    tile_db = ic.tile_db(5, 5)
    print(f"\nFirst routing entry in logic tile at (5, 5):")
    for entry in tile_db:
        if len(entry) >= 4 and entry[1] in ("routing", "buffer"):
            print(f"  Bits: {entry[0]}")
            print(f"  Type: {entry[1]}")
            print(f"  Source: {entry[2]}")
            print(f"  Target: {entry[3]}")
            # Try to write it
            success = write_edge_config_to_tile(ic, 5, 5, entry[2], entry[3])
            if success:
                print(f"  ✓ Successfully enabled connection")
                print_tile_bits(ic.tile(5, 5), highlight_bits=entry[0])
            break
