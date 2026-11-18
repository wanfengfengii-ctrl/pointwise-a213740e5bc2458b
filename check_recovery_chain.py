"""End-to-end check of the recovery chain, run by ``verify.py``.

The script builds the published V1 fixture, closes the station stores, then
recovers, publishes, reopens, exports and audits from the field ledger alone.
It exits non-zero on any disagreement.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from ledger.admission import publish_recovery
from ledger.export import export_result
from ledger.recovery_audit import audit_recovery
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.replay import recover_points
from recovery_cases import BASE_REFS, TARGETS, check_seed, seed_ledger
from source.sample_map import SparseSamples


class CheckFailed(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        ledger_path = root / 'field.sqlite'
        with closing(ResultStore(ledger_path)) as ledger:
            revision = seed_ledger(ledger, root / 'station.sqlite')
        require(Path(root / 'station.sqlite').exists(), 'V1 fixture was not built')

        with closing(ResultStore(ledger_path)) as ledger:
            check_seed(ledger, revision)

            base = recover_points(ledger, SparseSamples(revision, {}), BASE_REFS, TARGETS)
            require([row['status'] for row in base['rows']] ==
                    ['recovered', 'recovered', 'missing', 'missing'],
                    'base classification changed')
            require(base['rows'][0]['value'] == [3, 1] and base['rows'][1]['value'] == [2, 1],
                    'base recovered values changed')

            solved = recover_points(ledger, SparseSamples(revision, {3: 7}), BASE_REFS, TARGETS)
            require(solved['rows'][2]['value'] == [1, 1], 'x2 should recover to 1')
            require(solved['rows'][3]['status'] == 'measured', 'x3 should be measured')

            edge = recover_points(ledger, SparseSamples(revision, {}), (('edge', 3),), (3,))
            require(edge['rows'] == [{'index': 3, 'status': 'recovered', 'value': [7, 1],
                                      'terms': [['row', 'edge', 3, [1, 1]]]}],
                    'edge recovery changed')

            saved = publish_recovery(ledger, 'REC-1', solved)
            require(saved['format'] == 'wave-recovery-v1', 'recovery format changed')
            require(publish_recovery(ledger, 'REC-1', solved) == saved, 'replay changed')
            exported = export_result(ledger, 'REC-1')
            legacy_exported = export_result(ledger, 'sum')

        with closing(ResultStore(ledger_path)) as ledger:
            require(read_result(ledger, 'REC-1') == saved, 'reopened recovery changed')
            require(export_result(ledger, 'REC-1') == exported, 'reopened export changed')
            require(export_result(ledger, 'sum') == legacy_exported, 'legacy export changed')
            require(read_result(ledger, 'sum').rows[0].value == 5, 'legacy row changed')
            audit = audit_recovery(ledger, 'REC-1')
            require(audit['status_counts'] == {'measured': 1, 'recovered': 3, 'missing': 0},
                    'audit classification changed')
            for entry in audit['evidence']:
                require(entry['total'] == solved['rows'][entry['index']]['value'],
                        'audit total disagrees with the recovered value')
            for name in ('sum', 'difference', 'later', 'edge', 'sum-copy', 'conflict', 'foreign'):
                read_result(ledger, name)

        with closing(sqlite3.connect(ledger_path)) as database:
            counts = {table: database.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                      for table in ('result_headers', 'recovery_headers')}
        require(counts == {'result_headers': 8, 'recovery_headers': 1}, 'ledger row counts changed')

    print(json.dumps({'recovery_chain': 'ok', 'revision_seeded': True, 'export_bytes': len(exported)},
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
