from ledger.recovery_codec import decode_recovery_record
from ledger.report_codec import ArchivedResult, decode_archive_binding, decode_archived_row


def _read_v1(store, result_id):
    binding, rows = store.fetch(result_id)
    return ArchivedResult(result_id, decode_archive_binding(binding),
                          tuple(decode_archived_row(row) for row in rows))


def read_result(store, result_id):
    """Read a V1 result or a recovery result from the same ledger.

    A recovery result comes back as a plain dictionary carrying its public
    fields plus ``result_id`` and ``format``.  Reading never recomputes a
    recovery: the stored binding and body are decoded as they were written.
    """
    if not isinstance(result_id, str):
        raise ValueError('invalid result identifier')
    try:
        return _read_v1(store, result_id)
    except KeyError:
        pass
    fetch_recovery = getattr(store, 'fetch_recovery', None)
    if fetch_recovery is None:
        raise KeyError(result_id)
    try:
        binding, body = fetch_recovery(result_id)
    except KeyError:
        raise KeyError(result_id) from None
    return decode_recovery_record(result_id, binding, body)
