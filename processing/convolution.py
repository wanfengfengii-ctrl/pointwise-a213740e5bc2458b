from fractions import Fraction

from exchange.manifest import single_stage_terms
from processing.result_rows import MissingRow, ValueRow


def evaluate_single_point(package, index, values):
    missing = []
    value = Fraction(0)
    for source, weight in single_stage_terms(index, package.length, package.taps):
        if source in values:
            value += weight * values[source]
        else:
            missing.append(source)
    if missing:
        return MissingRow(index, tuple(missing))
    return ValueRow(index, value)
