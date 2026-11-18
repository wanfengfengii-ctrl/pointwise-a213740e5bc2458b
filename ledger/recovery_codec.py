"""Storage and export codec for recovery archives.

A recovery archive is stored as two independent byte strings:

* the *binding* holds the frozen request inputs
  (``revision``, ``length``, ``row_refs``, ``samples``, ``targets``);
* the *body* holds the per-target public rows, including the linear evidence
  attached to recovered rows.

Both are canonical JSON: sorted keys, reduced ``[numerator, denominator]``
pairs and the documented sequence orders.  V1 archives keep their own
``wave-result-v1`` encoding untouched.
"""

import json

RECOVERY_FORMAT = 'wave-recovery-v1'

_BINDING_FIELDS = ('revision', 'length', 'row_refs', 'samples', 'targets')


def _dump(document):
    return json.dumps(document, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _load(payload, label):
    try:
        return json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'stored recovery {label} is not valid JSON') from exc


def encode_recovery_binding(binding):
    return _dump(binding)


def encode_recovery_body(rows):
    return _dump(rows)


def decode_recovery_binding(payload):
    document = _load(payload, 'binding')
    if not isinstance(document, dict) or document.keys() != set(_BINDING_FIELDS):
        raise ValueError('stored recovery binding has unexpected fields')
    if not isinstance(document['revision'], str) or not document['revision'].strip():
        raise ValueError('stored recovery binding has an invalid revision')
    if type(document['length']) is not int or document['length'] <= 0:
        raise ValueError('stored recovery binding has an invalid length')
    if not isinstance(document['row_refs'], list) or not document['row_refs']:
        raise ValueError('stored recovery binding has no row references')
    if not isinstance(document['samples'], list) or not isinstance(document['targets'], list):
        raise ValueError('stored recovery binding has invalid sample or target lists')
    return {field: document[field] for field in _BINDING_FIELDS}


def decode_recovery_body(payload):
    rows = _load(payload, 'body')
    if not isinstance(rows, list):
        raise ValueError('stored recovery body is not a row list')
    for row in rows:
        if not isinstance(row, dict) or type(row.get('index')) is not int:
            raise ValueError('stored recovery body has an invalid row')
        if row.get('status') not in {'measured', 'recovered', 'missing'}:
            raise ValueError('stored recovery body has an invalid status')
    return rows


def decode_recovery_record(result_id, binding_payload, body_payload):
    binding = decode_recovery_binding(binding_payload)
    rows = decode_recovery_body(body_payload)
    return {
        'result_id': result_id,
        'format': RECOVERY_FORMAT,
        **binding,
        'rows': rows,
    }


def encode_recovery_result(record):
    return _dump(record)
