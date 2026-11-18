"""Independent ledger-side audit of a published recovery result.

``audit_recovery`` reopens a stored recovery record and re-derives everything
from the archived V1 rows and the measurements carried by the credential.  It
does not use any auxiliary field: only the public binding and body are
re-checked, so a successor can confirm the values and the missing points
without trusting the original recovery computation.
"""

from fractions import Fraction

from ledger.report_reader import read_result
from processing.recovery import (MEASURED, MISSING, RECOVERED, verify_candidate)

_PUBLIC_FIELDS = ('revision', 'length', 'row_refs', 'samples', 'targets', 'rows')


def audit_recovery(ledger, result_id):
    record = read_result(ledger, result_id)
    if not isinstance(record, dict):
        raise ValueError(f'{result_id!r} is not a recovery result')
    if record.get('format') != 'wave-recovery-v1':
        raise ValueError(f'{result_id!r} does not carry the recovery format')
    candidate = {field: record[field] for field in _PUBLIC_FIELDS}
    verified, _, _ = verify_candidate(ledger, candidate)
    if verified != candidate:
        raise ValueError('stored recovery record is not canonical')
    counts = {MEASURED: 0, RECOVERED: 0, MISSING: 0}
    for row in verified['rows']:
        counts[row['status']] += 1
    evidence = []
    for row in verified['rows']:
        if row['status'] != RECOVERED:
            continue
        total = Fraction(0)
        contributions = []
        for term in row['terms']:
            if term[0] == 'row':
                saved = read_result(ledger, term[1])
                origin = next(item for item in saved.rows if item.index == term[2])
                coefficient = Fraction(*term[3])
                contribution = coefficient * origin.value
                contributions.append({'source': 'row', 'result_id': term[1],
                                      'output': term[2],
                                      'archived': [origin.value.numerator, origin.value.denominator]})
            else:
                coefficient = Fraction(*term[2])
                measured = {index: Fraction(*parts) for index, parts in verified['samples']}
                contribution = coefficient * measured[term[1]]
                contributions.append({'source': 'sample', 'index': term[1]})
            total += contribution
        if total != Fraction(*row['value']):
            raise ValueError('evidence contribution does not match the recovered value')
        evidence.append({'index': row['index'], 'contributions': contributions,
                         'total': [total.numerator, total.denominator]})
    return {
        'result_id': result_id,
        'revision': verified['revision'],
        'length': verified['length'],
        'row_refs': verified['row_refs'],
        'samples': verified['samples'],
        'targets': verified['targets'],
        'status_counts': counts,
        'evidence': evidence,
    }
