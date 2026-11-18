import copy
import json
from contextlib import closing
from fractions import Fraction

from ledger.admission import publish_recovery, publish_result
from ledger.export import export_result
from ledger.recovery_audit import audit_recovery
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.replay import recover_points
from recovery_cases import BASE_REFS, TARGETS, check_seed, seed_ledger
from source.sample_map import SparseSamples
from tests.test_exchange import StationCase


class RecoveryCase(StationCase):
    def seeded(self):
        with closing(ResultStore(self.ledger_path)) as ledger:
            revision = seed_ledger(ledger, self.station_path)
        with closing(ResultStore(self.ledger_path)) as ledger:
            check_seed(ledger, revision)
        return revision

    def candidate(self, samples=None, refs=BASE_REFS, targets=TARGETS):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            return recover_points(ledger, SparseSamples(revision, samples or {}), refs, targets)

    @staticmethod
    def row(candidate, index):
        return next(row for row in candidate['rows'] if row['index'] == index)


class RecoverTests(RecoveryCase):
    def test_base_two_unknowns_rest_missing(self):
        candidate = self.candidate()
        self.assertEqual(candidate['row_refs'],
                         [['difference', 0], ['later', 2], ['sum', 0]])
        self.assertEqual(candidate['samples'], [])
        self.assertEqual(candidate['targets'], [0, 1, 2, 3])
        self.assertEqual([row['status'] for row in candidate['rows']],
                         ['recovered', 'recovered', 'missing', 'missing'])
        self.assertEqual(self.row(candidate, 0)['value'], [3, 1])
        self.assertEqual(self.row(candidate, 1)['value'], [2, 1])
        self.assertEqual(set(self.row(candidate, 2)), {'index', 'status'})
        self.assertEqual(set(self.row(candidate, 3)), {'index', 'status'})
        for index in (0, 1):
            row = self.row(candidate, index)
            self.assertEqual(set(row), {'index', 'status', 'value', 'terms'})

    def test_measurement_resolves_missing_point(self):
        candidate = self.candidate({3: 7})
        self.assertEqual(self.row(candidate, 3), {'index': 3, 'status': 'measured',
                                                  'value': [7, 1]})
        recovered = self.row(candidate, 2)
        self.assertEqual(recovered['status'], 'recovered')
        self.assertEqual(recovered['value'], [1, 1])
        self.assertIn(['sample', 3, [-1, 1]], recovered['terms'])
        self.assertIn(['row', 'later', 2, [1, 1]], recovered['terms'])

    def test_equivalent_solution_pair(self):
        # (3, 2, 8, 0) and (3, 2, 1, 7) both solve the equations; only 0 and 1
        # are forced, so 2 and 3 stay missing.
        first = self.candidate()
        self.assertEqual((self.row(first, 2)['status'], self.row(first, 3)['status']),
                         ('missing', 'missing'))

    def test_single_edge_row(self):
        candidate = self.candidate(refs=(('edge', 3),), targets=(3,))
        self.assertEqual(candidate['row_refs'], [['edge', 3]])
        self.assertEqual(candidate['rows'],
                         [{'index': 3, 'status': 'recovered', 'value': [7, 1],
                           'terms': [['row', 'edge', 3, [1, 1]]]}])

    def test_equivalent_archived_row_allowed(self):
        candidate = self.candidate(refs=(('sum-copy', 0), ('difference', 0)), targets=(0, 1))
        self.assertEqual(candidate['row_refs'], [['difference', 0], ['sum-copy', 0]])
        self.assertEqual(self.row(candidate, 0)['terms'],
                         [['row', 'difference', 0, [1, 2]], ['row', 'sum-copy', 0, [1, 2]]])

    def test_empty_targets_still_checks_consistency(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {}),
                                       (('sum',0), ('difference',0)), ())
            self.assertEqual(candidate['rows'], [])
            with self.assertRaises(ValueError):
                recover_points(ledger, SparseSamples(revision, {}),
                               (('sum',0), ('conflict',0)), ())

    def test_rejects_conflict_foreign_and_missing_rows(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            for refs, error in (((('sum', 0), ('conflict', 0)), ValueError),
                                ((('foreign', 0),), ValueError),
                                ((('missing', 0),), ValueError),
                                ((('unknown', 0),), KeyError)):
                with self.subTest(refs=refs), self.assertRaises(error):
                    recover_points(ledger, SparseSamples(revision, {}), refs, (0,))

    def test_rejects_inconsistent_measurement(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            with self.assertRaises(ValueError):
                recover_points(ledger, SparseSamples(revision, {0: 4, 1: 4}), (('sum', 0),), (0, 1))

    def test_input_validation(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            samples = SparseSamples(revision, {})
            bad_requests = (
                ((), (0,)), (('sum', 'x'), (0,)), (('sum', 0, 1), (0,)),
                (('sum', -1), (0,)), (('sum', True), (0,)),
                (('sum', 0), (0, 0)), (('sum', 0), (4,)), (('sum', 0), (True,)),
                (('sum', 0), ('0',)),
            )
            for refs, targets in bad_requests:
                with self.subTest(refs=refs, targets=targets), self.assertRaises(ValueError):
                    recover_points(ledger, samples, refs, targets)
            duplicate = (('sum', 0), ('sum', 0))
            with self.assertRaises(ValueError):
                recover_points(ledger, samples, duplicate, (0,))
            with self.assertRaises(ValueError):
                recover_points(ledger, SparseSamples(revision, {0: 0, True: 1}), (('sum', 0),), ())

    def test_rejects_mixed_length_and_revision(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            with self.assertRaises(ValueError):
                recover_points(ledger, SparseSamples('R-unknown', {}), (('sum', 0),), (0,))
            with self.assertRaises(ValueError):
                recover_points(ledger, SparseSamples(revision, {0: 1}), (('missing', 0),), (0,))


class PublishRecoveryTests(RecoveryCase):
    def publish(self, result_id='REC', candidate=None, before_commit=None):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = candidate or recover_points(ledger, SparseSamples(revision, {3: 7}),
                                                    BASE_REFS, TARGETS)
            return publish_recovery(ledger, result_id, candidate, before_commit=before_commit)

    def test_roundtrip_and_replay(self):
        saved = self.publish()
        self.assertEqual(saved['result_id'], 'REC')
        self.assertEqual(saved['format'], 'wave-recovery-v1')
        self.assertEqual(set(saved), {'result_id', 'format', 'revision', 'length',
                                      'row_refs', 'samples', 'targets', 'rows'})
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'REC'), saved)
            self.assertIsNot(read_result(ledger, 'REC'), read_result(ledger, 'REC'))
            exported = export_result(ledger, 'REC')
            self.assertEqual(export_result(ledger, 'REC'), exported)
            document = json.loads(exported)
            self.assertEqual(document['format'], 'wave-recovery-v1')
            self.assertEqual(document['rows'], saved['rows'])
            self.assertEqual(publish_recovery(ledger, 'REC', saved), saved)
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(export_result(ledger, 'REC'), exported)
            self.assertEqual(read_result(ledger, 'REC'), saved)

    def test_readback_is_copied(self):
        saved = self.publish()
        with closing(ResultStore(self.ledger_path)) as ledger:
            copied = read_result(ledger, 'REC')
        copied['rows'].clear()
        copied['targets'].append(99)
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'REC'), saved)

    def test_tampered_candidates_rejected(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            base = recover_points(ledger, SparseSamples(revision, {3: 7}), BASE_REFS, TARGETS)
            self.assertEqual(self.row(base, 0)['status'], 'recovered')
            broken = []
            candidate = copy.deepcopy(base)
            self.row(candidate, 0)['status'] = 'missing'
            self.row(candidate, 0).pop('value')
            self.row(candidate, 0).pop('terms')
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            self.row(candidate, 0)['value'] = [4, 1]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            self.row(candidate, 2)['value'] = [8, 1]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            self.row(candidate, 2)['terms'] = [['row', 'later', 2, [1, 1]]]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            candidate['row_refs'] = [['difference', 0], ['later', 2], ['sum-copy', 0]]
            self.row(candidate, 0)['terms'][1] = ['row', 'sum-copy', 0, [1, 2]]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            candidate['row_refs'] = [['difference', 0], ['foreign', 0], ['later', 2]]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            candidate['samples'] = [[3, [8, 1]]]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            candidate['length'] = 5
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            candidate['targets'] = [0, 0, 1, 2, 3]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            candidate['rows'] = candidate['rows'][:-1]
            broken.append(candidate)
            candidate = copy.deepcopy(base)
            candidate['rows'][0]['value'] = [3.0, 1]
            broken.append(candidate)
            for candidate in broken:
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    publish_recovery(ledger, 'BAD', candidate)
            with self.assertRaises(KeyError):
                read_result(ledger, 'BAD')

    def test_conflicting_replay_rejected(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {3: 7}), BASE_REFS, TARGETS)
            publish_recovery(ledger, 'REC', candidate)
            other = recover_points(ledger, SparseSamples(revision, {}), BASE_REFS, TARGETS)
            with self.assertRaises(ValueError):
                publish_recovery(ledger, 'REC', other)

    def test_empty_targets_publish(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {}), BASE_REFS, ())
            saved = publish_recovery(ledger, 'EMPTY', candidate)
            self.assertEqual(saved['rows'], [])
            self.assertEqual(saved['targets'], [])
            self.assertEqual(json.loads(export_result(ledger, 'EMPTY'))['rows'], [])

    def test_equivalent_alternative_combination_accepted(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {}),
                                       (('difference', 0), ('sum-copy', 0)), (0, 1))
            saved = publish_recovery(ledger, 'ALT', candidate)
            self.assertEqual(saved['row_refs'], [['difference', 0], ['sum-copy', 0]])
            # Declaring both same-value archived rows is equally valid.
            both = recover_points(ledger, SparseSamples(revision, {}),
                                  (('sum', 0), ('sum-copy', 0), ('difference', 0)), (0, 1))
            archived = publish_recovery(ledger, 'ALT2', both)
            self.assertEqual(archived['rows'][0]['value'], [3, 1])
            # The same formal result is accepted under another identifier.
            replacement = recover_points(ledger, SparseSamples(revision, {}),
                                         (('difference', 0), ('sum-copy', 0)), (0, 1))
            publish_recovery(ledger, 'ALT3', replacement)

    def test_conflicting_equations_rejected(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {}), (('difference', 0),), (0, 1))
            candidate['row_refs'] = [['conflict', 0], ['difference', 0], ['sum', 0]]
            self.row(candidate, 0)['terms'] = [['row', 'difference', 0, [1, 2]],
                                               ['row', 'sum', 0, [1, 2]]]
            self.row(candidate, 1)['terms'] = [['row', 'difference', 0, [-1, 2]],
                                               ['row', 'sum', 0, [1, 2]]]
            with self.assertRaises(ValueError):
                publish_recovery(ledger, 'CONFLICT', candidate)

    def test_identifier_collision_with_v1(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {}), BASE_REFS, TARGETS)
            with self.assertRaises(ValueError):
                publish_recovery(ledger, 'sum', candidate)

    def test_recovery_cannot_serve_as_source(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {}), BASE_REFS, TARGETS)
            publish_recovery(ledger, 'REC', candidate)
            with self.assertRaises(ValueError):
                recover_points(ledger, SparseSamples(revision, {}), (('REC', 0),), (0,))
            stored = read_result(ledger, 'REC')
            forged = dict(stored, target='ignored')
            forged['rows'] = [dict(row, note='aux') for row in stored['rows']]
            forged['row_refs'] = [['REC', 0], ['difference', 0], ['later', 2]]
            with self.assertRaises(ValueError):
                publish_recovery(ledger, 'FORGED', forged)

    def test_unknown_identifier(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            with self.assertRaises(KeyError):
                read_result(ledger, 'not-stored')
            with self.assertRaises(KeyError):
                export_result(ledger, 'not-stored')
            self.assertFalse(ledger.has_recovery('not-stored'))

    def test_failed_publish_is_retryable(self):
        class Interrupted(RuntimeError):
            pass

        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            candidate = recover_points(ledger, SparseSamples(revision, {3: 7}),
                                       BASE_REFS, TARGETS)

            def interrupt():
                with closing(ResultStore(self.ledger_path)) as observer:
                    with self.assertRaises(KeyError):
                        read_result(observer, 'REC')
                    self.assertEqual(read_result(observer, 'sum').package.length, 4)
                raise Interrupted()

            with self.assertRaises(Interrupted):
                publish_recovery(ledger, 'REC', candidate, before_commit=interrupt)
        with closing(ResultStore(self.ledger_path)) as ledger:
            with self.assertRaises(KeyError):
                read_result(ledger, 'REC')
            retried = publish_recovery(ledger, 'REC', candidate)
            self.assertEqual(retried['rows'], candidate['rows'])
            self.assertEqual(read_result(ledger, 'sum').rows[0].value, Fraction(5))

    def test_audit_reconstructs_from_ledger(self):
        saved = self.publish()
        with closing(ResultStore(self.ledger_path)) as ledger:
            audit = audit_recovery(ledger, 'REC')
            self.assertEqual(audit['status_counts'], {'measured': 1, 'recovered': 3, 'missing': 0})
            for entry in audit['evidence']:
                self.assertEqual(entry['total'], self.row(saved, entry['index'])['value'])
            self.assertEqual([entry['index'] for entry in audit['evidence']], [0, 1, 2])
            with self.assertRaises(ValueError):
                audit_recovery(ledger, 'sum')


class LegacyCompatibilityTests(RecoveryCase):
    def test_v1_untouched_next_to_recovery(self):
        revision = self.seeded()
        with closing(ResultStore(self.ledger_path)) as ledger:
            before = {name: read_result(ledger, name) for name in
                      ('sum', 'sum-copy', 'difference', 'later', 'edge', 'conflict',
                       'foreign', 'missing')}
            before_export = {name: export_result(ledger, name) for name in before}
            candidate = recover_points(ledger, SparseSamples(revision, {}), BASE_REFS, TARGETS)
            publish_recovery(ledger, 'REC', candidate)
        with closing(ResultStore(self.ledger_path)) as ledger:
            for name, saved in before.items():
                self.assertEqual(read_result(ledger, name), saved)
                self.assertEqual(export_result(ledger, name), before_export[name])
            # A V1 publish may not reuse a recovery identifier either.
            with self.assertRaises(ValueError):
                publish_result(ledger, 'REC', before['sum'].package, before['sum'].rows)
