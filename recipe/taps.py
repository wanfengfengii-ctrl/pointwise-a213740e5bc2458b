from collections.abc import Mapping

from source.sample_map import parse_rational, parse_rational_parts, rational_parts


def normalize_taps(taps):
    entries = taps.items() if isinstance(taps, Mapping) else taps
    try:
        entries = iter(entries)
    except TypeError as exc:
        raise ValueError('expected single-stage tap entries') from exc
    weights = {}
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError('expected an offset and a weight')
        offset, weight = entry
        if type(offset) is not int or offset in weights:
            raise ValueError('invalid or duplicate tap offset')
        weights[offset] = parse_rational(weight)
    return tuple((offset, weight) for offset, weight in sorted(weights.items()) if weight)


def encode_taps(taps):
    return [[offset, *rational_parts(weight)] for offset, weight in taps]


def decode_taps(entries):
    if not isinstance(entries, list):
        raise ValueError('expected a frozen tap array')
    taps = []
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError('invalid frozen tap')
        offset, numerator, denominator = entry
        taps.append((offset, parse_rational_parts(numerator, denominator)))
    normalized = normalize_taps(taps)
    if tuple(taps) != normalized:
        raise ValueError('frozen taps must be ordered and nonzero')
    return normalized
