import json

from source.sample_map import SparseSamples, parse_rational_parts, rational_parts


_SAMPLE_FORMAT = 'wave-samples-v1'


def encode_sample_transfer(samples):
    if not isinstance(samples, SparseSamples):
        raise ValueError('expected revision-bound samples')
    document = {
        'format': _SAMPLE_FORMAT,
        'revision': samples.revision,
        'samples': [[index, *rational_parts(value)] for index, value in samples.samples.items()],
    }
    return json.dumps(document, sort_keys=True, separators=(',', ':')).encode('utf-8')


def decode_sample_transfer(payload):
    try:
        document = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid sample transfer JSON') from exc
    if not isinstance(document, dict) or document.keys() != {'format', 'revision', 'samples'}:
        raise ValueError('invalid sample transfer fields')
    if document['format'] != _SAMPLE_FORMAT or not isinstance(document['samples'], list):
        raise ValueError('unsupported sample transfer format')
    entries = []
    for row in document['samples']:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError('invalid sample transfer entry')
        index, numerator, denominator = row
        entries.append((index, parse_rational_parts(numerator, denominator)))
    return SparseSamples(document['revision'], entries)
