import json
from contextlib import ExitStack, closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from exchange.issue_store import WindowIssueStore, export_window
from exchange.prepare import prepare_window
from ledger.admission import publish_result
from ledger.export import export_result
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.replay import run_window
from processing.result_rows import MissingRow, ValueRow
from recipe.catalog import register_recipe
from recipe.revision_store import RecipeStore
from source.import_wave import import_revision, import_wave_file
from source.read_samples import read_samples
from source.revisions import RevisionStore
from source.sample_transfer import decode_sample_transfer, encode_sample_transfer


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def stage_window(directory, label, revisions, recipes, issues, revision, version):
    package = prepare_window(revisions, recipes, issues, revision, version, 0, 3)
    samples = read_samples(revisions, package.revision, package.required_samples)
    window_file = directory / f'{label}.window.json'
    sample_file = directory / f'{label}.samples.json'
    window_file.write_bytes(export_window(issues, package.issue_id))
    sample_file.write_bytes(encode_sample_transfer(samples))
    check(package.required_samples == (0, 1, 2), 'unexpected sample manifest')
    return window_file, sample_file


def review_and_archive(ledger_path, result_id, transfer):
    window_file, sample_file = transfer
    payload = window_file.read_bytes()
    result = run_window(payload, decode_sample_transfer(sample_file.read_bytes()))
    with closing(ResultStore(ledger_path)) as ledger:
        ledger.initialize()
        archived = publish_result(ledger, result_id, payload, result)
    return archived


def main():
    examples = Path(__file__).resolve().parent / 'examples'
    definition = json.loads((examples / 'neighbor_mean.json').read_text(encoding='utf-8'))
    with TemporaryDirectory() as directory:
        directory = Path(directory)
        station_path = directory / 'station.sqlite'
        ledger_path = directory / 'review.sqlite'
        with ExitStack() as stack:
            revisions, recipes, issues = [stack.enter_context(closing(kind(station_path)))
                                          for kind in (RevisionStore, RecipeStore, WindowIssueStore)]
            for store in (revisions, recipes, issues):
                store.initialize()
            original = import_wave_file(revisions, examples / 'acquisition.json')
            version = register_recipe(recipes, **definition)
            first = stage_window(directory, 'first', revisions, recipes, issues, original, version)
        first_archive = review_and_archive(ledger_path, 'A1', first)
        with ExitStack() as stack:
            revisions, recipes, issues = [stack.enter_context(closing(kind(station_path)))
                                          for kind in (RevisionStore, RecipeStore, WindowIssueStore)]
            for store in (revisions, recipes, issues):
                store.initialize()
            base = revisions.get_revision(original)
            corrected = import_revision(revisions, base.source, base.length, base.unit, {1: 3, 2: 9}, original)
            check(revisions.current_revision(base.source) == corrected, 'correction not published')
            check(dict(read_samples(revisions, original, (0, 1, 2)).samples) == {0: 2, 2: 7},
                  'original revision changed')
            second = stage_window(directory, 'second', revisions, recipes, issues, corrected, version)
        second_archive = review_and_archive(ledger_path, 'A2', second)
        with closing(ResultStore(ledger_path)) as ledger:
            reopened = [read_result(ledger, result_id) for result_id in ('A1', 'A2')]
            check(reopened == [first_archive, second_archive], 'reopened archives changed')
            check([record.package.revision for record in reopened] == [original, corrected], 'archive revision mismatch')
            check(reopened[0].rows == (MissingRow(0, (1,)), MissingRow(1, (1,)), ValueRow(2, Fraction(7, 2))),
                  'incorrect original result')
            check(reopened[1].rows == (ValueRow(0, Fraction(5, 2)), ValueRow(1, Fraction(6)), ValueRow(2, Fraction(9, 2))),
                  'incorrect corrected result')
            for record in reopened:
                document = json.loads(export_result(ledger, record.result_id))
                summary = {'result_id': document['result_id'], 'unit': document['package']['output_unit'],
                           'required_samples': document['package']['required_samples'], 'rows': document['rows']}
                print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        demonstrate_recovery(directory)
    return 0


def demonstrate_recovery(directory):
    """Partial recovery, source outage, and an export read back from the ledger."""
    from ledger.admission import publish_recovery
    from ledger.recovery_audit import audit_recovery
    from processing.replay import recover_points
    from recovery_cases import BASE_REFS, TARGETS, seed_ledger
    from source.sample_map import SparseSamples

    directory = Path(directory)
    station_path = directory / 'recovery-station.sqlite'
    ledger_path = directory / 'recovery-field.sqlite'
    with closing(ResultStore(ledger_path)) as ledger:
        revision = seed_ledger(ledger, station_path)
    # The station stores are closed now; only the field ledger remains.
    station_path.unlink()
    with closing(ResultStore(ledger_path)) as ledger:
        partial = recover_points(ledger, SparseSamples(revision, {}), BASE_REFS, TARGETS)
        print(json.dumps({'stage': 'partial', 'candidate': partial}, ensure_ascii=False, sort_keys=True))
        publish_recovery(ledger, 'REC-1', partial)
        solved = recover_points(ledger, SparseSamples(revision, {3: 7}), BASE_REFS, TARGETS)
        print(json.dumps({'stage': 'solved', 'candidate': solved}, ensure_ascii=False, sort_keys=True))
        publish_recovery(ledger, 'REC-2', solved)
    with closing(ResultStore(ledger_path)) as ledger:
        for result_id in ('REC-1', 'REC-2'):
            exported = json.loads(export_result(ledger, result_id))
            audit = audit_recovery(ledger, result_id)
            print(json.dumps({
                'stage': 'reopened',
                'result_id': result_id,
                'format': exported['format'],
                'rows': exported['rows'],
                'evidence': audit['evidence'],
                'status_counts': audit['status_counts'],
            }, ensure_ascii=False, sort_keys=True))
        legacy = read_result(ledger, 'sum')
        print(json.dumps({'stage': 'legacy', 'result_id': 'sum',
                          'rows': [{'index': row.index, 'value': [row.value.numerator,
                                                                  row.value.denominator]}
                                   for row in legacy.rows]}, sort_keys=True))


if __name__ == '__main__':
    raise SystemExit(main())
