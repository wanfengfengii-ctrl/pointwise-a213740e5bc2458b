import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing, contextmanager
from fractions import Fraction
from pathlib import Path

from exchange.codec import decode_window
from exchange.issue_store import WindowIssueStore, export_window
from exchange.prepare import prepare_window
from processing.replay import run_window
from processing.result_rows import ValueRow
from recipe.catalog import register_recipe
from recipe.revision_store import RecipeStore
from source.import_wave import import_revision
from source.read_samples import read_samples
from source.revisions import RevisionStore
from source.sample_transfer import decode_sample_transfer, encode_sample_transfer


class StationCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.station_path = self.root / 'station.sqlite'
        self.ledger_path = self.root / 'review.sqlite'

    @contextmanager
    def station(self):
        with ExitStack() as stack:
            stores = tuple(stack.enter_context(closing(kind(self.station_path)))
                           for kind in (RevisionStore, RecipeStore, WindowIssueStore))
            for store in stores:
                store.initialize()
            yield stores

    def issue_count(self):
        with closing(sqlite3.connect(self.station_path)) as connection:
            return connection.execute('SELECT count(*) FROM window_issues').fetchone()[0]

    def write_transfer(self, stem, payload, samples):
        window_path = self.root / f'{stem}.window.json'
        samples_path = self.root / f'{stem}.samples.json'
        window_path.write_bytes(payload)
        samples_path.write_bytes(encode_sample_transfer(samples))
        return window_path, samples_path

    @staticmethod
    def run_transfer(paths):
        window_path, samples_path = paths
        return run_window(window_path.read_bytes(), decode_sample_transfer(samples_path.read_bytes()))


class ExchangeTests(StationCase):
    def test_prepare_single_stage(self):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', 3, 'mm/s', {0: 2, 1: 3, 2: 7})
            version = register_recipe(recipes, 'sum', 'mm/s', 'mm/s', {0: 1, 1: 1})
            package = prepare_window(revisions, recipes, issues, revision, version, 0, 2)
            payload = export_window(issues, package.issue_id)
            samples = read_samples(revisions, package.revision, package.required_samples)
        self.assertEqual((package.revision, package.recipe_version), (revision, version))
        self.assertEqual(package.required_samples, (0, 1, 2))
        self.assertEqual(decode_window(payload), package)
        self.assertEqual(run_window(payload, samples).rows, (ValueRow(0, Fraction(5)), ValueRow(1, Fraction(10))))

    def test_fixed_versions(self):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', 2, 'mm/s', {0: 4, 1: 8})
            old_version = register_recipe(recipes, 'gain', 'mm/s', 'scaled', {0: '1/2'})
            old = prepare_window(revisions, recipes, issues, revision, old_version, 0, 1)
            original = export_window(issues, old.issue_id)
            new_version = register_recipe(recipes, 'gain', 'mm/s', 'scaled', {0: 3})
        with self.station() as (revisions, recipes, issues):
            refreshed = prepare_window(revisions, recipes, issues, revision, old_version, 0, 1)
            new = prepare_window(revisions, recipes, issues, revision, new_version, 0, 1)
            self.assertEqual(export_window(issues, old.issue_id), original)
            self.assertEqual(recipes.get_version(old_version).taps, ((0, Fraction(1, 2)),))
            samples = read_samples(revisions, revision, (0,))
        self.assertNotEqual(old_version, new_version)
        self.assertEqual(run_window(refreshed, samples).rows, (ValueRow(0, Fraction(2)),))
        self.assertEqual(run_window(new, samples).rows, (ValueRow(0, Fraction(12)),))
        self.assertEqual(new.units.output_unit, 'scaled')

    def test_recipe_validation(self):
        with self.station() as (revisions, recipes, issues):
            version = register_recipe(recipes, 'scaled sum', 'mm/s', 'scaled', {2: 0, 0: '0.125', -1: '-1/3'})
            self.assertEqual(recipes.get_version(version).taps, ((-1, Fraction(-1, 3)), (0, Fraction(1, 8))))
            invalid = (
                ('', 'mm/s', 'scaled', {0: 1}),
                ('gain', ' ', 'scaled', {0: 1}),
                ('gain', 'mm/s', None, {0: 1}),
                ('gain', 'mm/s', 'scaled', {True: 1}),
                ('gain', 'mm/s', 'scaled', {0: '1/0'}),
                ('gain', 'mm/s', 'scaled', {0: 0.5}),
                ('gain', 'mm/s', 'scaled', [(0, 0), (0, 1)]),
            )
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    register_recipe(recipes, *args)
            revision = import_revision(revisions, 'table', 2, 'mm/s', {0: 8})
            package = prepare_window(revisions, recipes, issues, revision, version, 0, 1)
            self.assertEqual(package.required_samples, (0,))
        with closing(sqlite3.connect(self.station_path)) as database:
            self.assertEqual(database.execute('SELECT count(*) FROM recipe_versions').fetchone()[0], 1)

    def test_empty_window(self):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', 2, 'mm/s', {})
            version = register_recipe(recipes, 'sum', 'mm/s', 'mm/s', {0: 1, 1: 1})
            package = prepare_window(revisions, recipes, issues, revision, version, 1, 1)
            self.assertEqual(package.required_samples, ())
            self.assertEqual(decode_window(export_window(issues, package.issue_id)), package)

    def test_invalid_signout(self):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', 2, 'mm/s', {})
            version = register_recipe(recipes, 'copy', 'mm/s', 'mm/s', {0: 1})
            valid = prepare_window(revisions, recipes, issues, revision, version, 0, 1)
            cases = (
                (revision, version, 1, 0, ValueError),
                (revision, version, 0, 3, ValueError),
                (revision, version, -1, 0, ValueError),
                (revision, version, False, 1, ValueError),
                ('unknown', version, 0, 1, KeyError),
                (revision, 'unknown', 0, 1, KeyError),
            )
            for source, recipe, lo, hi, error in cases:
                with self.subTest(source=source, recipe=recipe, lo=lo, hi=hi), self.assertRaises(error):
                    prepare_window(revisions, recipes, issues, source, recipe, lo, hi)
            with self.assertRaises(KeyError):
                export_window(issues, 'unknown')
            self.assertEqual(decode_window(export_window(issues, valid.issue_id)), valid)
        self.assertEqual(self.issue_count(), 1)

    def test_unit_conflict(self):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', 2, 'mm/s', {0: 1})
            valid = register_recipe(recipes, 'convert', 'mm/s', 'scaled', {0: 1})
            invalid = register_recipe(recipes, 'other', 'm/s', 'mm/s', {0: 1})
            package = prepare_window(revisions, recipes, issues, revision, valid, 0, 2)
            original = export_window(issues, package.issue_id)
            with self.assertRaises(ValueError):
                prepare_window(revisions, recipes, issues, revision, invalid, 0, 2)
        with self.station() as (_, _, issues):
            self.assertEqual(export_window(issues, package.issue_id), original)
        self.assertEqual(self.issue_count(), 1)
