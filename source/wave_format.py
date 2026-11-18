import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class WaveInput:
    source: str
    length: int
    unit: str
    samples: tuple
    base_revision: str | None = None


def decode_wave_file(path):
    raw = Path(path).read_bytes()
    try:
        document = json.loads(raw, parse_float=Decimal)
    except (ValueError, ArithmeticError) as exc:
        raise ValueError('invalid acquisition JSON') from exc
    required = {'source', 'length', 'unit', 'samples'}
    if not isinstance(document, dict) or not required <= document.keys():
        raise ValueError('missing acquisition fields')
    if document.keys() - required - {'base_revision'}:
        raise ValueError('unknown acquisition fields')
    if not isinstance(document['samples'], list):
        raise ValueError('expected an acquisition sample array')
    return WaveInput(
        document['source'], document['length'], document['unit'],
        tuple(document['samples']), document.get('base_revision'),
    )
