from ledger.recovery_codec import encode_recovery_result
from ledger.report_codec import encode_archived_result
from ledger.report_reader import read_result


def export_result(store, result_id):
    saved = read_result(store, result_id)
    if isinstance(saved, dict):
        return encode_recovery_result(saved)
    return encode_archived_result(saved)
