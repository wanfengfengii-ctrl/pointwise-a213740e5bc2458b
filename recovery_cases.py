from contextlib import ExitStack, closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from exchange.issue_store import WindowIssueStore, export_window
from exchange.prepare import prepare_window
from ledger.admission import publish_result
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.replay import run_window
from processing.result_rows import MissingRow, ValueRow
from recipe.catalog import register_recipe
from recipe.revision_store import RecipeStore
from source.import_wave import import_revision
from source.read_samples import read_samples
from source.revisions import RevisionStore
from source.sample_map import SparseSamples
from source.sample_transfer import decode_sample_transfer, encode_sample_transfer


BASE_REFS = (("difference", 0), ("later", 2), ("sum", 0))
TARGETS = (0, 1, 2, 3)


def seed_ledger(ledger, station_path):
    with ExitStack() as stack:
        revisions, recipes, issues = (
            stack.enter_context(closing(store(station_path)))
            for store in (RevisionStore, RecipeStore, WindowIssueStore)
        )
        for store in (revisions, recipes, issues):
            store.initialize()
        original = import_revision(revisions, "shaker", 4, "mm/s", {0: 3, 1: 2, 2: 1, 3: 7})
        corrected = import_revision(revisions, "shaker", 4, "mm/s", {2: 9}, original)
        pair = register_recipe(recipes, "pair", "mm/s", "mm/s", {0: 1, 1: 1})
        difference = register_recipe(recipes, "difference", "mm/s", "mm/s", {0: 1, 1: -1})
        transfers = {}
        for name, revision, version, output in (
            ("sum", original, pair, 0),
            ("sum-copy", original, pair, 0),
            ("difference", original, difference, 0),
            ("later", original, pair, 2),
            ("edge", original, pair, 3),
            ("foreign", corrected, pair, 0),
        ):
            package = prepare_window(revisions, recipes, issues, revision, version, output, output + 1)
            samples = read_samples(revisions, revision, package.required_samples)
            transfers[name] = export_window(issues, package.issue_id), encode_sample_transfer(samples)
    ledger.initialize()
    for name, (payload, samples) in transfers.items():
        publish_result(ledger, name, payload, run_window(payload, decode_sample_transfer(samples)))
    payload = transfers["sum"][0]
    for name, values in (("missing", {0: 3}), ("conflict", {0: 4, 1: 2})):
        publish_result(ledger, name, payload, run_window(payload, SparseSamples(original, values)))
    return original


def check_seed(ledger, original):
    expected = (
        ("sum", 0, 5), ("sum-copy", 0, 5), ("difference", 0, 1),
        ("later", 2, 8), ("edge", 3, 7), ("conflict", 0, 6), ("foreign", 0, 5),
    )
    for name, output, value in expected:
        saved = read_result(ledger, name)
        if saved.rows != (ValueRow(output, Fraction(value)),):
            raise RuntimeError(f"wrong V1 rows for {name}: {saved.rows!r}")
        expected_original = name != "foreign"
        if (saved.package.revision == original) != expected_original or saved.package.length != 4:
            raise RuntimeError(f"wrong V1 binding for {name}")
    if read_result(ledger, "missing").rows != (MissingRow(0, (1,)),):
        raise RuntimeError("missing control must be a V1 missing row")


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        ledger_path = root / "field.sqlite"
        with closing(ResultStore(ledger_path)) as ledger:
            original = seed_ledger(ledger, root / "station.sqlite")
        with closing(ResultStore(ledger_path)) as ledger:
            check_seed(ledger, original)
            for name, _ in BASE_REFS:
                saved = read_result(ledger, name)
                print(name, saved.rows[0].index, saved.rows[0].value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
