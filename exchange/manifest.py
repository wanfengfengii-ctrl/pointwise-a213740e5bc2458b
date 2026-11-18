from dataclasses import dataclass
from fractions import Fraction

from exchange.window import Window, is_record_index, validate_window
from recipe.taps import normalize_taps
from recipe.units import RecipeUnits


@dataclass(frozen=True)
class WindowPackage:
    issue_id: str
    revision: str
    length: int
    recipe_version: str
    units: RecipeUnits
    window: Window
    taps: tuple[tuple[int, Fraction], ...]
    required_samples: tuple[int, ...]


def single_stage_terms(output, length, taps):
    for offset, weight in taps:
        index = output + offset
        if weight and is_record_index(index, length):
            yield index, weight


def build_sample_manifest(length, window, taps):
    required = {
        index
        for output in window.indices()
        for index, _ in single_stage_terms(output, length, taps)
    }
    return tuple(sorted(required))


def validate_package_manifest(package):
    if not isinstance(package, WindowPackage):
        raise ValueError('expected a V1 window package')
    for identifier in (package.issue_id, package.revision, package.recipe_version):
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError('invalid window identifier')
    if not isinstance(package.units, RecipeUnits) or not isinstance(package.window, Window):
        raise ValueError('invalid window units or bounds')
    validate_window(package.length, package.window.lo, package.window.hi)
    if not isinstance(package.taps, tuple) or normalize_taps(package.taps) != package.taps:
        raise ValueError('invalid frozen single-stage taps')
    if any(not isinstance(weight, Fraction) for _, weight in package.taps):
        raise ValueError('expected frozen rational weights')
    required = package.required_samples
    if not isinstance(required, tuple) or any(type(index) is not int for index in required):
        raise ValueError('invalid sample manifest')
    if required != build_sample_manifest(package.length, package.window, package.taps):
        raise ValueError('sample manifest disagrees with frozen taps and window')
