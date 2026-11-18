from ledger.report_codec import ArchivedResult, decode_archive_binding, decode_archived_row


def read_result(store, result_id):
    binding, rows = store.fetch(result_id)
    return ArchivedResult(result_id, decode_archive_binding(binding), tuple(decode_archived_row(row) for row in rows))
