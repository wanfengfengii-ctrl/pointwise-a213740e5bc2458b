import sqlite3
from dataclasses import dataclass
from uuid import uuid4

from source.sample_map import parse_rational


@dataclass(frozen=True)
class Revision:
    revision: str
    source: str
    length: int
    unit: str
    base_revision: str | None


class RevisionStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path)
        self._db.execute('PRAGMA foreign_keys = ON')

    def close(self):
        self._db.close()

    def initialize(self):
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS wave_revisions (
                revision TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                record_length TEXT NOT NULL,
                unit TEXT NOT NULL,
                base_revision TEXT REFERENCES wave_revisions(revision)
            );
            CREATE TABLE IF NOT EXISTS wave_samples (
                revision TEXT NOT NULL REFERENCES wave_revisions(revision),
                sample_index TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (revision, sample_index)
            );
            CREATE TABLE IF NOT EXISTS wave_current (
                source TEXT PRIMARY KEY,
                revision TEXT NOT NULL REFERENCES wave_revisions(revision)
            );
        ''')

    def save_revision(self, source, length, unit, samples, base_revision=None):
        revision = f'R-{uuid4().hex}'
        with self._db:
            if base_revision is not None:
                base = self.get_revision(base_revision)
                if base.source != source:
                    raise KeyError(base_revision)
                if (base.length, base.unit) != (length, unit):
                    raise ValueError('correction must retain the base length and unit')
            self._db.execute(
                'INSERT INTO wave_revisions VALUES (?, ?, ?, ?, ?)',
                (revision, source, str(length), unit, base_revision),
            )
            if base_revision is not None:
                self._db.execute('''
                    INSERT INTO wave_samples (revision, sample_index, value)
                    SELECT ?, sample_index, value FROM wave_samples WHERE revision = ?
                ''', (revision, base_revision))
            self._db.executemany('''
                INSERT INTO wave_samples (revision, sample_index, value) VALUES (?, ?, ?)
                ON CONFLICT(revision, sample_index) DO UPDATE SET value = excluded.value
            ''', ((revision, str(index), str(value)) for index, value in samples.items()))
            self._db.execute('''
                INSERT INTO wave_current (source, revision) VALUES (?, ?)
                ON CONFLICT(source) DO UPDATE SET revision = excluded.revision
            ''', (source, revision))
        return revision

    def get_revision(self, revision):
        if not isinstance(revision, str):
            raise ValueError('invalid revision identifier')
        row = self._db.execute('''
            SELECT source, record_length, unit, base_revision
            FROM wave_revisions WHERE revision = ?
        ''', (revision,)).fetchone()
        if row is None:
            raise KeyError(revision)
        source, length, unit, base = row
        return Revision(revision, source, int(length), unit, base)

    def current_revision(self, source):
        row = self._db.execute('SELECT revision FROM wave_current WHERE source = ?', (source,)).fetchone()
        if row is None:
            raise KeyError(source)
        return row[0]

    def read_entries(self, revision, indices):
        entries = {}
        for index in indices:
            row = self._db.execute('''
                SELECT value FROM wave_samples WHERE revision = ? AND sample_index = ?
            ''', (revision, str(index))).fetchone()
            if row is not None:
                entries[index] = parse_rational(row[0])
        return entries
