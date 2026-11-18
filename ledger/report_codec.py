import json
from dataclasses import dataclass

from exchange.codec import decode_window, encode_window
from exchange.manifest import WindowPackage
from processing.result_rows import MissingRow, ResultRow, ValueRow, validate_row_coverage
from source.sample_map import parse_rational_parts, rational_parts


@dataclass(frozen=True)
class ArchivedResult:
    result_id: str
    package: WindowPackage
    rows: tuple[ResultRow, ...]

    def __post_init__(self):
        if not isinstance(self.result_id, str) or not self.result_id.strip():
            raise ValueError('invalid result identifier')
        validate_row_coverage(self.package, self.rows)


def _encode(document):
    return json.dumps(document, sort_keys=True, separators=(',', ':')).encode('utf-8')


def encode_archive_binding(package):
    return encode_window(package)


def decode_archive_binding(payload):
    return decode_window(payload)


def encode_archived_row(row):
    if isinstance(row, ValueRow):
        return _encode({'index': row.index, 'value': rational_parts(row.value)})
    if isinstance(row, MissingRow):
        return _encode({'index': row.index, 'missing': row.missing})
    raise ValueError('invalid archived row')


def decode_archived_row(payload):
    try:
        document = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid archived row JSON') from exc
    if not isinstance(document, dict) or type(document.get('index')) is not int or document['index'] < 0:
        raise ValueError('invalid archived output index')
    index = document['index']
    if document.keys() == {'index', 'value'}:
        value = document['value']
        if isinstance(value, list) and len(value) == 2:
            return ValueRow(index, parse_rational_parts(*value))
    if document.keys() == {'index', 'missing'}:
        missing = document['missing']
        if (isinstance(missing, list) and missing and all(type(item) is int and item >= 0 for item in missing)
                and missing == sorted(set(missing))):
            return MissingRow(index, tuple(missing))
    raise ValueError('invalid archived row fields')


def encode_archived_result(result):
    return _encode({
        'format': 'wave-result-v1',
        'result_id': result.result_id,
        'package': json.loads(encode_archive_binding(result.package)),
        'rows': [json.loads(encode_archived_row(row)) for row in result.rows],
    })
