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
            CREATE TABLE IF NOT EXISTS recovery_headers (
                result_id TEXT PRIMARY KEY,
                binding BLOB NOT NULL,
                body BLOB NOT NULL
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
            if self._has_recovery(result_id):
                raise ValueError(f'result identifier {result_id!r} is already used by a recovery')
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

    # -- recovery archives -------------------------------------------------

    def _recovery_table_exists(self):
        row = self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'recovery_headers'"
        ).fetchone()
        return row is not None

    def _has_recovery(self, result_id):
        if not self._recovery_table_exists():
            return False
        return self._db.execute(
            'SELECT 1 FROM recovery_headers WHERE result_id = ?', (result_id,)
        ).fetchone() is not None

    def publish_recovery(self, result_id, binding, body, *, before_commit=None):
        if not isinstance(result_id, str):
            raise ValueError('invalid result identifier')
        with self._db:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                self.fetch(result_id)
            except KeyError:
                v1_present = False
            else:
                v1_present = True
            if v1_present:
                raise ValueError(f'result identifier {result_id!r} is already used by a V1 result')
            if self._has_recovery(result_id):
                stored = self._db.execute(
                    'SELECT binding, body FROM recovery_headers WHERE result_id = ?',
                    (result_id,),
                ).fetchone()
                if stored != (binding, body):
                    raise ValueError(f'conflicting recovery for {result_id!r}')
                return
            self._db.execute(
                'INSERT INTO recovery_headers VALUES (?, ?, ?)', (result_id, binding, body)
            )
            if before_commit is not None:
                before_commit()

    def fetch_recovery(self, result_id):
        if not isinstance(result_id, str):
            raise ValueError('invalid result identifier')
        if not self._recovery_table_exists():
            raise KeyError(result_id)
        row = self._db.execute(
            'SELECT binding, body FROM recovery_headers WHERE result_id = ?', (result_id,)
        ).fetchone()
        if row is None:
            raise KeyError(result_id)
        return row[0], row[1]

    def has_recovery(self, result_id):
        return self._has_recovery(result_id)
