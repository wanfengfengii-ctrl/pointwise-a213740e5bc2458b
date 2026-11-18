import json
import sqlite3
from dataclasses import dataclass
from fractions import Fraction
from uuid import uuid4

from recipe.taps import decode_taps, encode_taps
from recipe.units import RecipeUnits


@dataclass(frozen=True)
class RecipeVersion:
    version: str
    name: str
    units: RecipeUnits
    taps: tuple[tuple[int, Fraction], ...]


class RecipeStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path)

    def close(self):
        self._db.close()

    def initialize(self):
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS recipe_versions (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                input_unit TEXT NOT NULL,
                output_unit TEXT NOT NULL,
                taps TEXT NOT NULL
            )
        ''')

    def save_version(self, name, units, taps):
        version = f'P-{uuid4().hex}'
        payload = json.dumps(encode_taps(taps), separators=(',', ':'))
        with self._db:
            self._db.execute(
                'INSERT INTO recipe_versions VALUES (?, ?, ?, ?, ?)',
                (version, name, units.input_unit, units.output_unit, payload),
            )
        return version

    def get_version(self, version):
        if not isinstance(version, str):
            raise ValueError('invalid recipe version identifier')
        row = self._db.execute('''
            SELECT name, input_unit, output_unit, taps FROM recipe_versions WHERE version = ?
        ''', (version,)).fetchone()
        if row is None:
            raise KeyError(version)
        name, input_unit, output_unit, taps = row
        return RecipeVersion(version, name, RecipeUnits(input_unit, output_unit), decode_taps(json.loads(taps)))
