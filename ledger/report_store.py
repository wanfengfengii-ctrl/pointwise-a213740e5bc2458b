import sqlite3

from ledger.report_codec import encode_archive_binding, encode_archived_row


class ResultStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path)
        self._db.execute('PRAGMA foreign_keys = ON')

    def close(self):
        self._db.close()

    def initialize(self):
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS result_headers (
                result_id TEXT PRIMARY KEY,
                binding BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS result_rows (
                result_id TEXT NOT NULL REFERENCES result_headers(result_id),
                position INTEGER NOT NULL,
                payload BLOB NOT NULL,
                PRIMARY KEY (result_id, position)
            );
        ''')

    def publish(self, result, *, before_commit=None):
        result_id = result.result_id
        binding = encode_archive_binding(result.package)
        rows = tuple(encode_archived_row(row) for row in result.rows)
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                previous = self.fetch(result_id)
            except KeyError:
                previous = None
            if previous is not None:
                if previous != (binding, rows):
                    raise ValueError(f'conflicting result for {result_id!r}')
                return
            self._db.execute('INSERT INTO result_headers VALUES (?, ?)', (result_id, binding))
            self._db.executemany(
                'INSERT INTO result_rows VALUES (?, ?, ?)',
                ((result_id, position, row) for position, row in enumerate(rows)),
            )
            if before_commit is not None:
                before_commit()

    def fetch(self, result_id):
        if not isinstance(result_id, str):
            raise ValueError('invalid result identifier')
        records = self._db.execute('''
            SELECT h.binding, r.payload
            FROM result_headers AS h LEFT JOIN result_rows AS r USING (result_id)
            WHERE h.result_id = ? ORDER BY r.position
        ''', (result_id,)).fetchall()
        if not records:
            raise KeyError(result_id)
        return records[0][0], tuple(payload for _, payload in records if payload is not None)
