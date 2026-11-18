import json
from contextlib import closing
from fractions import Fraction

from exchange.issue_store import export_window
from exchange.prepare import prepare_window
from ledger.admission import publish_result
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.replay import run_window
from processing.result_rows import MissingRow, ValueRow
from recipe.catalog import register_recipe
from source.import_wave import import_revision
from source.read_samples import read_samples
from source.sample_map import SparseSamples
from source.sample_transfer import decode_sample_transfer
from tests.test_exchange import StationCase


class ReplayTests(StationCase):
    def capture(self, values, taps, lo, hi, length=3):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', length, 'mm/s', values)
            version = register_recipe(recipes, 'review', 'mm/s', 'mm/s', taps)
            package = prepare_window(revisions, recipes, issues, revision, version, lo, hi)
            payload = export_window(issues, package.issue_id)
            samples = read_samples(revisions, package.revision, package.required_samples)
            return package, self.write_transfer('review', payload, samples)

    def test_offline_fraction_and_edge(self):
        package, paths = self.capture({0: 2, 1: 3, 2: 7}, {0: '1/2', 1: '1/2'}, 1, 3)
        result = self.run_transfer(paths)
        self.assertEqual(package.required_samples, (1, 2))
        self.assertEqual(result.package, package)
        self.assertEqual(result.rows, (ValueRow(1, Fraction(5)), ValueRow(2, Fraction(7, 2))))

    def test_exact_thirds(self):
        _, paths = self.capture({0: 1}, {0: '1/3'}, 0, 1, length=1)
        row, = self.run_transfer(paths).rows
        self.assertIsInstance(row, ValueRow)
        self.assertIsInstance(row.value, Fraction)
        self.assertEqual((row.index, row.value.numerator, row.value.denominator), (0, 1, 3))

    def test_empty_outputs(self):
        for taps, lo, hi, expected in (
            ({0: 1}, 1, 1, ()),
            ({-10: 1, 10: -1}, 0, 2, (ValueRow(0, Fraction(0)), ValueRow(1, Fraction(0)))),
            ({}, 2, 3, (ValueRow(2, Fraction(0)),)),
        ):
            with self.subTest(taps=taps, lo=lo, hi=hi):
                package, paths = self.capture({}, taps, lo, hi)
                self.assertEqual(package.required_samples, ())
                self.assertEqual(self.run_transfer(paths).rows, expected)

    def test_invalid_package(self):
        _, (window_path, sample_path) = self.capture({0: 1, 1: 4}, {0: 1, 1: 1}, 0, 1)
        document = json.loads(window_path.read_bytes())
        samples = decode_sample_transfer(sample_path.read_bytes())
        for fields in (
            {'required_samples': [0]}, {'required_samples': [1, 0]}, {'required_samples': [False, 1]},
            {'window': [0, 4]}, {'window': {'lo': 0, 'hi': 1}}, {'version': 2},
            {'taps': [[0, 1, 0]]}, {'taps': [[0, 1, 1], [0, 2, 1]]},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                run_window(json.dumps(document | fields).encode(), samples)
        with self.assertRaises(ValueError):
            run_window(b'{', samples)

    def test_zero_and_missing(self):
        _, paths = self.capture({0: 0}, {0: 1}, 0, 2)
        self.assertEqual(self.run_transfer(paths).rows, (ValueRow(0, Fraction(0)), MissingRow(1, (1,))))

    def test_all_missing(self):
        _, paths = self.capture({0: 0}, {2: 1, 0: -3, 1: 2}, 0, 1)
        self.assertEqual(self.run_transfer(paths).rows, (MissingRow(0, (1, 2)),))

    def test_wrong_revision(self):
        with self.station() as (revisions, recipes, issues):
            old = import_revision(revisions, 'table', 2, 'mm/s', {0: 2, 1: 3})
            new = import_revision(revisions, 'table', 2, 'mm/s', {0: 8}, old)
            version = register_recipe(recipes, 'copy', 'mm/s', 'mm/s', {0: 1})
            package = prepare_window(revisions, recipes, issues, old, version, 0, 2)
            payload = export_window(issues, package.issue_id)
            correct = read_samples(revisions, old, package.required_samples)
            wrong = read_samples(revisions, new, package.required_samples)
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            result = run_window(payload, correct)
            self.assertEqual(result.rows, (ValueRow(0, Fraction(2)), ValueRow(1, Fraction(3))))
            archived = publish_result(ledger, 'old', payload, result)
            self.assertEqual(set(correct.samples), set(wrong.samples))
            with self.assertRaises(ValueError):
                run_window(payload, wrong)
            self.assertEqual(read_result(ledger, 'old'), archived)

    def test_invalid_index(self):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', 2, 'mm/s', {0: 3})
            version = register_recipe(recipes, 'copy', 'mm/s', 'mm/s', {0: 1})
            package = prepare_window(revisions, recipes, issues, revision, version, 0, 1)
            payload = export_window(issues, package.issue_id)
            for index in (-1, 2, True, '0'):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    read_samples(revisions, revision, (index,))
        with self.assertRaises(ValueError):
            run_window(payload, SparseSamples(revision, {0: 3, 2: 5}))
        self.assertEqual(run_window(payload, SparseSamples(revision, {0: 3, 1: 5})).rows,
                         (ValueRow(0, Fraction(3)),))
