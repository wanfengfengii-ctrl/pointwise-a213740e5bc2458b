from exchange.codec import decode_window
from exchange.manifest import WindowPackage
from ledger.recovery_codec import decode_recovery_record, encode_recovery_result
from ledger.report_codec import ArchivedResult, encode_archive_binding
from ledger.report_reader import read_result
from ledger.report_store import ResultStore
from processing.recovery import verify_candidate
from processing.result_rows import OfflineRows


def publish_result(store, result_id, package, rows, *, before_commit=None):
    frozen = package if isinstance(package, WindowPackage) else decode_window(package)
    binding = encode_archive_binding(frozen)
    if not isinstance(rows, OfflineRows) or encode_archive_binding(rows.package) != binding:
        raise ValueError('result rows belong to a different window package')
    result = ArchivedResult(result_id, frozen, rows.rows)
    store.publish(result, before_commit=before_commit)
    return read_result(store, result_id)


def _require_recovery_store(store):
    if not isinstance(store, ResultStore) or not hasattr(store, 'publish_recovery'):
        raise ValueError('recovery archives need a ResultStore')
    return store


def _check_identifier(result_id):
    if not isinstance(result_id, str):
        raise ValueError('invalid result identifier')
    if not result_id.strip():
        raise ValueError('invalid result identifier')
    return result_id


def publish_recovery(ledger, result_id, candidate, *, before_commit=None):
    """Publish a recovery result after re-deriving it from the ledger itself."""
    store = _require_recovery_store(ledger)
    _check_identifier(result_id)
    record, binding, body = verify_candidate(store, candidate)
    store.publish_recovery(result_id, binding, body, before_commit=before_commit)
    return read_recovery_result(store, result_id)


def read_recovery_result(store, result_id):
    store = _require_recovery_store(store)
    binding, body = store.fetch_recovery(result_id)
    return decode_recovery_record(result_id, binding, body)


def export_recovery_result(store, result_id):
    store = _require_recovery_store(store)
    return encode_recovery_result(read_recovery_result(store, result_id))
