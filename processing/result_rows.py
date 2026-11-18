from dataclasses import dataclass
from fractions import Fraction

from exchange.manifest import WindowPackage, single_stage_terms
from source.sample_map import parse_rational


@dataclass(frozen=True)
class ValueRow:
    index: int
    value: Fraction


@dataclass(frozen=True)
class MissingRow:
    index: int
    missing: tuple[int, ...]


ResultRow = ValueRow | MissingRow


@dataclass(frozen=True)
class OfflineRows:
    package: WindowPackage
    rows: tuple[ResultRow, ...]


def assemble_rows(package, rows):
    return OfflineRows(package, tuple(rows))


def validate_row_coverage(package, rows):
    if not isinstance(package, WindowPackage) or not isinstance(rows, tuple):
        raise ValueError('expected window-bound result rows')
    if len(rows) != package.window.hi - package.window.lo:
        raise ValueError('result rows must cover the entire window')
    for index, row in zip(package.window.indices(), rows):
        if not isinstance(row, (ValueRow, MissingRow)) or type(row.index) is not int or row.index != index:
            raise ValueError('result indices must cover the window in order')
        if isinstance(row, ValueRow):
            parse_rational(row.value)
            continue
        sources = {source for source, _ in single_stage_terms(index, package.length, package.taps)}
        missing = row.missing
        if not isinstance(missing, tuple) or not missing:
            raise ValueError('expected one or more missing source indices')
        if any(type(source) is not int or source not in sources for source in missing):
            raise ValueError('missing index is outside this output source set')
        if missing != tuple(sorted(set(missing))):
            raise ValueError('missing source indices must be unique and ordered')
