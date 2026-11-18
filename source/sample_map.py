from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType


def parse_rational(value):
    if type(value) is int or isinstance(value, (Fraction, Decimal, str)):
        try:
            return Fraction(value)
        except (ValueError, ArithmeticError) as exc:
            raise ValueError('invalid rational value') from exc
    raise ValueError('expected an exact rational value')


def rational_parts(value):
    value = parse_rational(value)
    return value.numerator, value.denominator


def parse_rational_parts(numerator, denominator):
    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        raise ValueError('invalid rational parts')
    return Fraction(numerator, denominator)


def validate_sample_index(index, length=None):
    if type(index) is not int or index < 0 or (length is not None and index >= length):
        raise ValueError('sample index outside record')
    return index


def normalize_samples(samples, length=None):
    entries = samples.items() if isinstance(samples, Mapping) else samples
    try:
        entries = iter(entries)
    except TypeError as exc:
        raise ValueError('expected sample entries') from exc
    normalized = {}
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError('expected an index and a sample value')
        index, value = entry
        validate_sample_index(index, length)
        if index in normalized:
            raise ValueError(f'duplicate sample index {index}')
        normalized[index] = parse_rational(value)
    return dict(sorted(normalized.items()))


@dataclass(frozen=True)
class SparseSamples:
    revision: str
    samples: Mapping[int, Fraction]

    def __post_init__(self):
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError('invalid sample revision')
        samples = MappingProxyType(normalize_samples(self.samples))
        object.__setattr__(self, 'samples', samples)
