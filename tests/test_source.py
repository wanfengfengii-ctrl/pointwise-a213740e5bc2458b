import json
import sqlite3
from contextlib import closing
from fractions import Fraction

from source.import_wave import import_revision, import_wave_file
from source.read_samples import read_samples
from tests.test_exchange import StationCase


class SourceTests(StationCase):
    def test_duplicate_index_rollback(self):
        with self.station() as (revisions, _, _):
            revision = import_revision(revisions, 'table', 3, 'mm/s', {0: 2, 2: 7})
            before = read_samples(revisions, revision, (0, 1, 2))
            path = self.root / 'correction.json'
            path.write_text(json.dumps({
                'source': 'table', 'length': 3, 'unit': 'mm/s',
                'base_revision': revision, 'samples': [[1, 3], [1, 8]],
            }), encoding='utf-8')
            with self.assertRaises(ValueError):
                import_wave_file(revisions, path)
        with self.station() as (revisions, _, _):
            self.assertEqual(revisions.current_revision('table'), revision)
            self.assertEqual(read_samples(revisions, revision, (0, 1, 2)), before)
        with closing(sqlite3.connect(self.station_path)) as database:
            self.assertEqual(database.execute('SELECT count(*) FROM wave_revisions').fetchone()[0], 1)

    def test_import_errors(self):
        path = self.root / 'wave.json'
        path.write_text('{"source":"table","length":3,"unit":"mm/s","samples":[[0,0],[2,0.1]]}', encoding='utf-8')
        with self.station() as (revisions, _, _):
            revision = import_wave_file(revisions, path)
            cases = (
                ('table', 3, 'mm/s', [(3, 4)], revision, ValueError),
                ('table', 3, 'mm/s', [(1, 'not rational')], revision, ValueError),
                ('table', 3, 'mm/s', [(1, 4)], 'unknown', KeyError),
                ('other', 3, 'mm/s', [(1, 4)], revision, KeyError),
                ('table', 4, 'mm/s', [(1, 4)], revision, ValueError),
                ('table', 3, 'm/s', [(1, 4)], revision, ValueError),
            )
            for *args, error in cases:
                with self.subTest(args=args), self.assertRaises(error):
                    import_revision(revisions, *args)
        with self.station() as (revisions, _, _):
            self.assertEqual(revisions.current_revision('table'), revision)
            collected = read_samples(revisions, revision, (2, 0, 2, 1))
            self.assertEqual(list(collected.samples.items()), [(0, Fraction(0)), (2, Fraction(1, 10))])
            with self.assertRaises(KeyError):
                read_samples(revisions, 'unknown', (0,))
