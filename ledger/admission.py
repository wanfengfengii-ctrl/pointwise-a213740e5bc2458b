from exchange.codec import decode_window
from exchange.manifest import WindowPackage
from ledger.report_codec import ArchivedResult, encode_archive_binding
from ledger.report_reader import read_result
from processing.result_rows import OfflineRows


def publish_result(store, result_id, package, rows, *, before_commit=None):
    frozen = package if isinstance(package, WindowPackage) else decode_window(package)
    binding = encode_archive_binding(frozen)
    if not isinstance(rows, OfflineRows) or encode_archive_binding(rows.package) != binding:
        raise ValueError('result rows belong to a different window package')
    result = ArchivedResult(result_id, frozen, rows.rows)
    store.publish(result, before_commit=before_commit)
    return read_result(store, result_id)
