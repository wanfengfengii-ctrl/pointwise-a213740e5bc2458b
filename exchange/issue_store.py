import sqlite3

from exchange.codec import encode_window


class WindowIssueStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path)

    def close(self):
        self._db.close()

    def initialize(self):
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS window_issues (
                issue_id TEXT PRIMARY KEY,
                payload BLOB NOT NULL
            )
        ''')

    def save(self, package):
        payload = encode_window(package)
        with self._db:
            self._db.execute('INSERT INTO window_issues VALUES (?, ?)', (package.issue_id, payload))

    def get_payload(self, issue_id):
        if not isinstance(issue_id, str):
            raise ValueError('invalid issue identifier')
        row = self._db.execute('SELECT payload FROM window_issues WHERE issue_id = ?', (issue_id,)).fetchone()
        if row is None:
            raise KeyError(issue_id)
        return row[0]


def export_window(store, issue_id):
    return store.get_payload(issue_id)
