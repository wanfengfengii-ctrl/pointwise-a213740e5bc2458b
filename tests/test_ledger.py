import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from fractions import Fraction

from exchange.issue_store import export_window
from exchange.prepare import prepare_window
from ledger.admission import publish_result
from ledger.export import export_result
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.replay import run_window
from processing.result_rows import MissingRow, ValueRow
from recipe.catalog import register_recipe
from source.import_wave import import_revision
from source.read_samples import read_samples
from source.sample_map import SparseSamples
from tests.test_exchange import StationCase


class PublishInterrupted(RuntimeError):
    pass


class LedgerTests(StationCase):
    def shipment(self, lo=0, hi=2):
        with self.station() as (revisions, recipes, issues):
            revision = import_revision(revisions, 'table', 3, 'mm/s', {0: 2, 1: 3, 2: 7})
            version = register_recipe(recipes, 'mean', 'mm/s', 'mm/s', {0: '1/2', 1: '1/2'})
            package = prepare_window(revisions, recipes, issues, revision, version, lo, hi)
            payload = export_window(issues, package.issue_id)
            samples = read_samples(revisions, revision, package.required_samples)
        return payload, samples

    def test_reopen_and_replay(self):
        payload, samples = self.shipment()
        rows = run_window(payload, samples)
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            first = publish_result(ledger, 'A1', payload, rows)
            equivalent = replace(rows, rows=(ValueRow(0, '10/4'), rows.rows[1]))
            self.assertEqual(publish_result(ledger, 'A1', payload, equivalent), first)
            exported = export_result(ledger, 'A1')
        with closing(ResultStore(self.ledger_path)) as reopened:
            copied = read_result(reopened, 'A1')
            self.assertEqual(copied, first)
            self.assertIsNot(copied, first)
            self.assertEqual(copied.package, rows.package)
            self.assertEqual(copied.rows, (ValueRow(0, Fraction(5, 2)), ValueRow(1, Fraction(5))))
            self.assertEqual(export_result(reopened, 'A1'), exported)
            self.assertEqual(json.loads(exported)['rows'], [{'index': 0, 'value': [5, 2]}, {'index': 1, 'value': [5, 1]}])
            with self.assertRaises(KeyError):
                export_result(reopened, 'unknown')
        with closing(sqlite3.connect(self.ledger_path)) as database:
            self.assertEqual(database.execute('SELECT count(*) FROM result_headers').fetchone()[0], 1)
            self.assertEqual(database.execute('SELECT count(*) FROM result_rows').fetchone()[0], 2)

    def test_content_conflict(self):
        payload, samples = self.shipment()
        complete = run_window(payload, samples)
        partial = run_window(payload, SparseSamples(samples.revision, {0: 2, 2: 7}))
        self.assertEqual(partial.rows, (MissingRow(0, (1,)), MissingRow(1, (1,))))
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            first = publish_result(ledger, 'A1', payload, complete)
            with self.assertRaises(ValueError):
                publish_result(ledger, 'A1', payload, partial)
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'A1'), first)

    def test_foreign_binding(self):
        payload, samples = self.shipment()
        first = run_window(payload, samples)
        with self.station() as (revisions, recipes, issues):
            old = first.package
            other = prepare_window(revisions, recipes, issues, old.revision, old.recipe_version, 0, 2)
        second = run_window(other, samples)
        self.assertEqual(first.rows, second.rows)
        self.assertNotEqual(first.package.issue_id, other.issue_id)
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            saved = publish_result(ledger, 'A1', payload, first)
            with self.assertRaises(ValueError):
                publish_result(ledger, 'foreign', payload, second)
            with self.assertRaises(ValueError):
                publish_result(ledger, 'A1', other, second)
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'A1'), saved)
            with self.assertRaises(KeyError):
                read_result(ledger, 'foreign')

    def test_row_coverage(self):
        payload, samples = self.shipment()
        rows = run_window(payload, samples)
        first, last = rows.rows
        bad_bodies = (
            (first,), (first, first), (last, first),
            (ValueRow(0, 'not a value'), last), (MissingRow(0, ()), last),
            (MissingRow(0, (1, 0)), last), (MissingRow(0, (1, 1)), last),
            (MissingRow(0, (2,)), last), ({'index': 0, 'value': 1, 'missing': [1]}, last),
        )
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            for body in bad_bodies:
                with self.subTest(body=body), self.assertRaises(ValueError):
                    publish_result(ledger, 'A1', payload, replace(rows, rows=body))
        with closing(ResultStore(self.ledger_path)) as ledger:
            with self.assertRaises(KeyError):
                read_result(ledger, 'A1')
            self.assertEqual(publish_result(ledger, 'A1', payload, rows).rows, rows.rows)

    def test_initialize_again(self):
        payload, samples = self.shipment()
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            first = publish_result(ledger, 'A1', payload, run_window(payload, samples))
            original = export_result(ledger, 'A1')
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            ledger.initialize()
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'A1'), first)
            self.assertEqual(export_result(ledger, 'A1'), original)

    def test_empty_archive(self):
        payload, samples = self.shipment(1, 1)
        rows = run_window(payload, samples)
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            first = publish_result(ledger, 'empty', payload, rows)
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'empty'), first)
            self.assertEqual(first.rows, ())
            self.assertEqual(first.package, rows.package)
            self.assertEqual(json.loads(export_result(ledger, 'empty'))['rows'], [])

    def test_failed_publish_retry(self):
        payload, samples = self.shipment()
        rows = run_window(payload, samples)
        with closing(ResultStore(self.ledger_path)) as ledger:
            ledger.initialize()
            old = publish_result(ledger, 'old', payload, rows)

            def interrupt_after_rows():
                with closing(ResultStore(self.ledger_path)) as observer:
                    self.assertEqual(read_result(observer, 'old'), old)
                    with self.assertRaises(KeyError):
                        read_result(observer, 'interrupted')
                raise PublishInterrupted('review station interrupted before commit')

            with self.assertRaises(PublishInterrupted):
                publish_result(ledger, 'interrupted', payload, rows, before_commit=interrupt_after_rows)
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'old'), old)
            with self.assertRaises(KeyError):
                read_result(ledger, 'interrupted')
            retried = publish_result(ledger, 'interrupted', payload, rows)
        with closing(ResultStore(self.ledger_path)) as ledger:
            self.assertEqual(read_result(ledger, 'interrupted'), retried)
            self.assertEqual(retried.rows, (ValueRow(0, Fraction(5, 2)), ValueRow(1, Fraction(5))))
