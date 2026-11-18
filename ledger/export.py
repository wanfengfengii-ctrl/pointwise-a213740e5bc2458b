from ledger.report_codec import encode_archived_result
from ledger.report_reader import read_result


def export_result(store, result_id):
    return encode_archived_result(read_result(store, result_id))
