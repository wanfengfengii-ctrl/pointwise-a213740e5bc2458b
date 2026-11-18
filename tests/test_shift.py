import json
from contextlib import closing
from fractions import Fraction

from exchange.issue_store import export_window
from exchange.prepare import prepare_window
from ledger.admission import publish_result
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.result_rows import MissingRow, ValueRow
from recipe.catalog import register_recipe
from source.import_wave import import_revision
from source.read_samples import read_samples
from tests.test_exchange import StationCase


class ShiftTests(StationCase):
    def test_correction_preserves_old_issue(self):
        with self.station() as (revisions, recipes, issues):
            old = import_revision(revisions, 'table', 3, 'mm/s', {0: 2, 2: 7})
            version = register_recipe(recipes, 'copy', 'mm/s', 'mm/s', {0: 1})
            first = prepare_window(revisions, recipes, issues, old, version, 2, 3)
            original = export_window(issues, first.issue_id)
            initial = read_samples(revisions, old, first.required_samples)
            original_paths = self.write_transfer('original', original, initial)
        original_rows = self.run_transfer(original_paths)
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            first_archive = publish_result(ledger, 'old', original, original_rows)
            self.assertEqual(first_archive.rows, (ValueRow(2, Fraction(7)),))
        with self.station() as (revisions, recipes, issues):
            new = import_revision(revisions, 'table', 3, 'mm/s', {2: 9}, old)
            second = prepare_window(revisions, recipes, issues, new, version, 2, 3)
            old_payload = export_window(issues, first.issue_id)
            new_payload = export_window(issues, second.issue_id)
            self.assertEqual(old_payload, original)
            old_samples = read_samples(revisions, first.revision, first.required_samples)
            new_samples = read_samples(revisions, second.revision, second.required_samples)
            old_paths = self.write_transfer('old', old_payload, old_samples)
            new_paths = self.write_transfer('new', new_payload, new_samples)
        old_rows, new_rows = self.run_transfer(old_paths), self.run_transfer(new_paths)
        self.assertEqual(tuple(sample.samples[2] for sample in (old_samples, new_samples)), (7, 9))
        self.assertEqual(old_rows.rows, (ValueRow(2, Fraction(7)),))
        self.assertEqual(new_rows.rows, (ValueRow(2, Fraction(9)),))
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(publish_result(ledger, 'old', old_payload, old_rows), first_archive)
            publish_result(ledger, 'new', new_payload, new_rows)
        with closing(ResultStore(self.ledger_path)) as ledger:
            archives = [read_result(ledger, result_id) for result_id in ('old', 'new')]
        self.assertEqual([report.package.revision for report in archives], [old, new])
        self.assertEqual([report.rows[0].value for report in archives], [7, 9])
        evidence = {
            'case_id': 'V9',
            'input': {'samples': [[0, 2], [2, 7]], 'base_correction': [[2, 9]], 'window': [2, 3], 'taps': [[0, 1]]},
            'expected': {'recollected': ['7', '9'], 'offline': ['7', '9']},
            'actual': {
                'recollected': [str(sample.samples[2]) for sample in (old_samples, new_samples)],
                'offline': [str(result.rows[0].value) for result in (old_rows, new_rows)],
            },
            'downstream_expected': {'reopened': ['7', '9'], 'original_revision_bindings': [True, True]},
            'downstream_actual': {
                'reopened': [str(report.rows[0].value) for report in archives],
                'original_revision_bindings': [report.package.revision == revision for report, revision in zip(archives, (old, new))],
            },
            'code_paths': ['source/import_wave.py', 'source/revisions.py', 'source/read_samples.py',
                           'exchange/prepare.py', 'processing/replay.py', 'ledger/report_reader.py'],
            'oracle': 'The identity tap reads index 2 of the named snapshot. The original is 7 and its explicit correction is 9.',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(evidence, sort_keys=True), flush=True)

    def test_explicit_base(self):
        with self.station() as (revisions, recipes, issues):
            original = import_revision(revisions, 'table', 3, 'mm/s', {0: 2, 2: 7})
            second = import_revision(revisions, 'table', 3, 'mm/s', {0: 4}, original)
            third = import_revision(revisions, 'table', 3, 'mm/s', {2: 9}, original)
            version = register_recipe(recipes, 'copy', 'mm/s', 'mm/s', {0: 1})
            revision_ids = (original, second, third)
            packages = [prepare_window(revisions, recipes, issues, revision, version, 0, 3)
                        for revision in revision_ids]
        expected = ({0: 2, 2: 7}, {0: 4, 2: 7}, {0: 2, 2: 9})
        transfers = []
        with self.station() as (revisions, recipes, issues):
            self.assertEqual(revisions.current_revision('table'), third)
            self.assertEqual(revisions.get_revision(third).base_revision, original)
            self.assertEqual(recipes.get_version(version).taps, ((0, Fraction(1)),))
            for position, (package, entries) in enumerate(zip(packages, expected)):
                samples = read_samples(revisions, package.revision, package.required_samples)
                self.assertEqual(dict(samples.samples), entries)
                payload = export_window(issues, package.issue_id)
                transfers.append(self.write_transfer(str(position), payload, samples))
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            for position, paths in enumerate(transfers):
                publish_result(ledger, str(position), paths[0].read_bytes(), self.run_transfer(paths))
        with closing(ResultStore(self.ledger_path)) as ledger:
            for position, (package, entries) in enumerate(zip(packages, expected)):
                archived = read_result(ledger, str(position))
                self.assertEqual(archived.package, package)
                self.assertEqual(archived.rows, (ValueRow(0, Fraction(entries[0])), MissingRow(1, (1,)),
                                                 ValueRow(2, Fraction(entries[2]))))
