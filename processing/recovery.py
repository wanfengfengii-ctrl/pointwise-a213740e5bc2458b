"""Exact rational recovery of missing source points from archived V1 rows.

The rules implemented here are the public ones from ``RECOVERY.md``:

* every direct source is an archived V1 ``ValueRow`` whose package shares the
  request revision and record length; the frozen single-stage taps of that
  package define the equation ``sum(weight * x[output + offset]) = value``
  with out-of-record terms dropped;
* every supplied measurement is the equation ``x[index] = value``;
* the whole system is solved over the rationals, even when no target is
  requested.  A target is ``recovered`` only when every solution gives the
  same value; otherwise it stays ``missing``.  A measured target is always
  ``measured``.

Nothing here trusts a candidate's own claim.  ``verify_candidate`` rebuilds
the equations from the ledger and checks the declared evidence independently.
"""

from fractions import Fraction

from ledger.report_reader import read_result
from source.sample_map import (SparseSamples, parse_rational, parse_rational_parts,
                               rational_parts)

MEASURED = 'measured'
RECOVERED = 'recovered'
MISSING = 'missing'

_PUBLIC_FIELDS = ('revision', 'length', 'row_refs', 'samples', 'targets', 'rows')


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------

def _sequence(value, label):
    if not isinstance(value, (list, tuple)):
        raise ValueError(f'invalid recovery {label}')
    return value


def _index(value, length, label):
    if type(value) is not int or not 0 <= value < length:
        raise ValueError(f'invalid recovery {label}')
    return value


def _parts(value, label='rational'):
    """Accept a stored ``[numerator, denominator]`` pair or an exact rational."""
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(f'invalid recovery {label}')
        return parse_rational_parts(value[0], value[1])
    try:
        return parse_rational(value)
    except ValueError:
        raise ValueError(f'invalid recovery {label}') from None


def _normalize_refs(row_refs):
    entries = _sequence(row_refs, 'row references')
    if not entries:
        raise ValueError('a recovery request needs at least one row reference')
    refs = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError('invalid recovery row reference')
        result_id, output = entry
        if not isinstance(result_id, str) or not result_id.strip():
            raise ValueError('invalid recovery row reference identifier')
        if type(output) is not int or output < 0:
            raise ValueError('invalid recovery row reference index')
        if (result_id, output) in seen:
            raise ValueError('duplicate recovery row reference')
        seen.add((result_id, output))
        refs.append((result_id, output))
    return tuple(sorted(refs))


def _normalize_samples(samples, length=None):
    entries = _sequence(samples, 'samples')
    values = {}
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError('invalid recovery sample')
        index, parts = entry
        if length is not None:
            _index(index, length, 'sample index')
        elif type(index) is not int or index < 0:
            raise ValueError('invalid recovery sample index')
        if index in values:
            raise ValueError('duplicate recovery sample index')
        values[index] = _parts(parts, 'sample value')
    return dict(sorted(values.items()))


def _normalize_targets(targets, length=None):
    entries = _sequence(targets, 'targets')
    values = []
    seen = set()
    for index in entries:
        if length is not None:
            _index(index, length, 'target index')
        elif type(index) is not int or index < 0:
            raise ValueError('invalid recovery target index')
        if index in seen:
            raise ValueError('duplicate recovery target index')
        seen.add(index)
        values.append(index)
    return tuple(sorted(values))


# ---------------------------------------------------------------------------
# Ledger row resolution
# ---------------------------------------------------------------------------

def _require_ledger(ledger):
    if not callable(getattr(ledger, 'fetch', None)):
        raise ValueError('recovery needs a ledger with archived results')
    return ledger


def resolve_refs(ledger, revision, row_refs):
    """Return the frozen taps and value of every referenced V1 row.

    Returns ``(rows, length)`` where ``rows`` is a tuple of
    ``(result_id, output, taps, value)`` in request order.
    """
    from processing.result_rows import ValueRow

    _require_ledger(ledger)
    resolved = []
    lengths = set()
    for result_id, output in row_refs:
        saved = read_result(ledger, result_id)  # unknown identifier -> KeyError
        if isinstance(saved, dict):
            raise ValueError('recovery results cannot serve as direct rows')
        if saved.package.revision != revision:
            raise ValueError('row package revision does not match the samples')
        lengths.add(saved.package.length)
        row = next((item for item in saved.rows if item.index == output), None)
        if row is None:
            raise ValueError('row reference index is outside its archived window')
        if not isinstance(row, ValueRow):
            raise ValueError('V1 missing rows cannot serve as direct equations')
        resolved.append((result_id, output, saved.package.taps, row.value))
    if len(lengths) != 1:
        raise ValueError('referenced rows must share one record length')
    length = lengths.pop()
    return tuple(resolved), length


def _row_terms(output, taps, length):
    return tuple((output + offset, weight) for offset, weight in taps
                 if 0 <= output + offset < length)


def build_equations(resolved, measured, length):
    """Return ``{source: (terms, rhs)}`` for every declared equation."""
    equations = {}
    for result_id, output, taps, value in resolved:
        equations[('row', result_id, output)] = (_row_terms(output, taps, length), value)
    for index, value in measured.items():
        equations[('sample', index)] = (((index, Fraction(1)),), value)
    return equations


# ---------------------------------------------------------------------------
# Gaussian elimination with provenance
# ---------------------------------------------------------------------------

def _solve(equations, length):
    """Reduce the system and return classification data.

    Returns ``(matrix, rhs, provenance, sources, pivots)``.  ``provenance[r]``
    records how reduced row ``r`` combines the original equations, so a
    determined target can be written as a linear combination of archived row
    values and supplied measurements only.
    """
    sources = list(equations)
    count = len(sources)
    matrix = []
    rhs = []
    provenance = []
    for position, source in enumerate(sources):
        terms, value = equations[source]
        row = [Fraction(0)] * length
        for variable, weight in terms:
            row[variable] += weight
        matrix.append(row)
        rhs.append(value)
        provenance.append([Fraction(1) if other == position else Fraction(0)
                           for other in range(count)])
    pivots = {}
    rank = 0
    for column in range(length):
        pivot = next((candidate for candidate in range(rank, count)
                      if matrix[candidate][column] != 0), None)
        if pivot is None:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        rhs[rank], rhs[pivot] = rhs[pivot], rhs[rank]
        provenance[rank], provenance[pivot] = provenance[pivot], provenance[rank]
        scale = matrix[rank][column]
        if scale != 1:
            inverse = Fraction(1) / scale
            matrix[rank] = [value * inverse for value in matrix[rank]]
            rhs[rank] = rhs[rank] * inverse
            provenance[rank] = [value * inverse for value in provenance[rank]]
        for other in range(count):
            factor = matrix[other][column]
            if other == rank or factor == 0:
                continue
            matrix[other] = [left - factor * right
                             for left, right in zip(matrix[other], matrix[rank])]
            rhs[other] = rhs[other] - factor * rhs[rank]
            provenance[other] = [left - factor * right
                                 for left, right in zip(provenance[other], provenance[rank])]
        pivots[column] = rank
        rank += 1
        if rank == count:
            break
    for position in range(count):
        if not any(matrix[position]) and rhs[position] != 0:
            raise ValueError('the recovery equations are inconsistent')
    return matrix, rhs, provenance, sources, pivots


def _is_determined(matrix, pivots, variable):
    if variable not in pivots:
        return False
    row = matrix[pivots[variable]]
    return all(value == 0 for column, value in enumerate(row) if column != variable)


def classify(equations, length, targets):
    """Return ``{target: (status, value, terms)}`` for the full system."""
    matrix, rhs, provenance, sources, pivots = _solve(equations, length)
    classification = {}
    for target in targets:
        source = ('sample', target)
        if source in equations:
            classification[target] = (MEASURED, equations[source][1], None)
            continue
        if not _is_determined(matrix, pivots, target):
            classification[target] = (MISSING, None, None)
            continue
        row = pivots[target]
        terms = []
        for position, coefficient in enumerate(provenance[row]):
            if coefficient == 0:
                continue
            origin = sources[position]
            if origin[0] == 'row':
                terms.append(['row', origin[1], origin[2], coefficient])
            else:
                terms.append(['sample', origin[1], coefficient])
        terms.sort(key=lambda term: (0, term[1], term[2]) if term[0] == 'row'
                   else (1, term[1]))
        classification[target] = (RECOVERED, rhs[row], terms)
    return classification


# ---------------------------------------------------------------------------
# Request entry point
# ---------------------------------------------------------------------------

def _public_term(term):
    if term[0] == 'row':
        return ['row', term[1], term[2], list(rational_parts(term[3]))]
    return ['sample', term[1], list(rational_parts(term[2]))]


def recover_points(ledger, samples, row_refs, targets):
    """Build a recovery candidate from the local ledger only."""
    if not isinstance(samples, SparseSamples):
        raise ValueError('expected revision-bound samples')
    revision = samples.revision
    refs = _normalize_refs(row_refs)
    resolved, length = resolve_refs(ledger, revision, refs)
    measured = _normalize_samples(list(samples.samples.items()), length)
    requested = _normalize_targets(targets, length)
    equations = build_equations(resolved, measured, length)
    classification = classify(equations, length, requested)
    rows = []
    for target in requested:
        status, value, terms = classification[target]
        if status == MEASURED:
            rows.append({'index': target, 'status': MEASURED,
                         'value': list(rational_parts(value))})
        elif status == RECOVERED:
            rows.append({'index': target, 'status': RECOVERED,
                         'value': list(rational_parts(value)),
                         'terms': [_public_term(term) for term in terms]})
        else:
            rows.append({'index': target, 'status': MISSING})
    return {
        'revision': revision,
        'length': length,
        'row_refs': [[result_id, output] for result_id, output in refs],
        'samples': [[index, list(rational_parts(value))]
                    for index, value in measured.items()],
        'targets': list(requested),
        'rows': rows,
    }


# ---------------------------------------------------------------------------
# Candidate verification (used by the publishing side)
# ---------------------------------------------------------------------------

def _normalize_terms(terms):
    """Canonicalise evidence terms.

    The public rule allows each source at most one non-zero coefficient, so
    repeated terms are tolerated only when all but one are zero; zeros carry
    no information and are dropped from the canonical form.
    """
    entries = _sequence(terms, 'evidence terms')
    if not entries:
        raise ValueError('recovered rows need at least one evidence term')
    kept = {}
    for term in entries:
        if not isinstance(term, (list, tuple)) or not term:
            raise ValueError('invalid evidence term')
        kind = term[0]
        if kind == 'row':
            if len(term) != 4:
                raise ValueError('invalid row evidence term')
            result_id, output, coefficient = term[1], term[2], term[3]
            if not isinstance(result_id, str) or not result_id.strip():
                raise ValueError('invalid evidence row identifier')
            if type(output) is not int or output < 0:
                raise ValueError('invalid evidence output index')
            source = ('row', result_id, output)
        elif kind == 'sample':
            if len(term) != 3:
                raise ValueError('invalid sample evidence term')
            index, coefficient = term[1], term[2]
            if type(index) is not int or index < 0:
                raise ValueError('invalid evidence sample index')
            source = ('sample', index)
        else:
            raise ValueError('invalid evidence term kind')
        value = _parts(coefficient, 'evidence coefficient')
        if value == 0:
            continue
        if source in kept:
            raise ValueError('evidence source has more than one non-zero coefficient')
        kept[source] = value
    if not kept:
        raise ValueError('evidence needs at least one non-zero term')
    parsed = sorted(kept.items(),
                    key=lambda item: (0, item[0][1], item[0][2]) if item[0][0] == 'row'
                    else (1, item[0][1]))
    return parsed


def _normalize_rows(rows):
    """Collect the public row fields; unknown auxiliary keys are ignored."""
    entries = _sequence(rows, 'rows')
    by_index = {}
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError('invalid recovery row')
        index = row.get('index')
        if type(index) is not int:
            raise ValueError('invalid recovery row index')
        if index in by_index:
            raise ValueError('duplicate recovery row')
        status = row.get('status')
        if status == MEASURED:
            if not {'index', 'status', 'value'} <= row.keys():
                raise ValueError('invalid measured row fields')
            by_index[index] = {'index': index, 'status': MEASURED,
                               'value': _parts(row['value'], 'measured value')}
        elif status == RECOVERED:
            if not {'index', 'status', 'value', 'terms'} <= row.keys():
                raise ValueError('invalid recovered row fields')
            by_index[index] = {'index': index, 'status': RECOVERED,
                               'value': _parts(row['value'], 'recovered value'),
                               'terms': _normalize_terms(row['terms'])}
        elif status == MISSING:
            if 'index' not in row or 'status' not in row:
                raise ValueError('invalid missing row fields')
            by_index[index] = {'index': index, 'status': MISSING}
        else:
            raise ValueError('invalid recovery row status')
    return by_index


def _check_evidence(target, value, terms, equations, length):
    coefficients = [Fraction(0)] * length
    total = Fraction(0)
    for source, coefficient in terms:
        if source not in equations:
            raise ValueError('evidence refers to an undeclared source')
        if coefficient == 0:
            continue
        source_terms, source_value = equations[source]
        for variable, weight in source_terms:
            coefficients[variable] += coefficient * weight
        total += coefficient * source_value
    expected = [Fraction(0)] * length
    expected[target] = Fraction(1)
    if coefficients != expected:
        raise ValueError('evidence combination does not reduce to the target')
    if total != value:
        raise ValueError('evidence combination does not equal the declared value')


def verify_candidate(ledger, candidate):
    """Re-derive everything from the ledger and return canonical artefacts.

    Returns ``(record, binding, body)`` where ``record`` is the public
    recovery record and the two byte strings are what the ledger stores.
    """
    from ledger.recovery_codec import encode_recovery_binding, encode_recovery_body

    if not isinstance(candidate, dict):
        raise ValueError('invalid recovery candidate')
    for field in _PUBLIC_FIELDS:
        if field not in candidate:
            raise ValueError(f'missing recovery field {field!r}')
    revision = candidate['revision']
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError('invalid recovery revision')
    declared_length = candidate['length']
    if type(declared_length) is not int or declared_length <= 0:
        raise ValueError('invalid recovery length')

    refs = _normalize_refs(candidate['row_refs'])
    resolved, length = resolve_refs(ledger, revision, refs)
    if length != declared_length:
        raise ValueError('declared recovery length disagrees with the archived rows')

    measured = _normalize_samples(candidate['samples'], length)
    requested = _normalize_targets(candidate['targets'], length)
    equations = build_equations(resolved, measured, length)
    classification = classify(equations, length, requested)

    declared = _normalize_rows(candidate['rows'])
    if sorted(declared) != list(requested):
        raise ValueError('recovery rows must cover exactly the targets')

    canonical_rows = []
    for target in requested:
        status, value, terms = classification[target]
        row = declared[target]
        if status == MEASURED:
            if row['status'] != MEASURED or row['value'] != value:
                raise ValueError('a measured target must be reported as measured')
            canonical_rows.append({'index': target, 'status': MEASURED,
                                   'value': list(rational_parts(value))})
        elif status == RECOVERED:
            if row['status'] != RECOVERED:
                raise ValueError('a uniquely recoverable target was left unresolved')
            if row['value'] != value:
                raise ValueError('recovered value disagrees with the equations')
            _check_evidence(target, row['value'], row['terms'], equations, length)
            canonical_rows.append({
                'index': target, 'status': RECOVERED,
                'value': list(rational_parts(row['value'])),
                'terms': [[source[0], *source[1:], list(rational_parts(coefficient))]
                          if source[0] == 'row'
                          else [source[0], source[1], list(rational_parts(coefficient))]
                          for source, coefficient in row['terms']],
            })
        else:
            if row['status'] != MISSING:
                raise ValueError('an under-determined target cannot be declared resolved')
            canonical_rows.append({'index': target, 'status': MISSING})

    binding = {
        'revision': revision,
        'length': length,
        'row_refs': [[result_id, output] for result_id, output in refs],
        'samples': [[index, list(rational_parts(value))]
                    for index, value in measured.items()],
        'targets': list(requested),
    }
    body = canonical_rows
    record = {**binding, 'rows': canonical_rows}
    return record, encode_recovery_binding(binding), encode_recovery_body(body)
