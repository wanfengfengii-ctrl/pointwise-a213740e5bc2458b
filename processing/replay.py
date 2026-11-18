from exchange.codec import decode_window
from exchange.manifest import WindowPackage, validate_package_manifest
from processing.convolution import evaluate_single_point
from processing.input_binding import bind_samples
from processing.result_rows import assemble_rows


def run_window(package, samples):
    if isinstance(package, WindowPackage):
        validate_package_manifest(package)
    else:
        package = decode_window(package)
    values = bind_samples(package, samples)
    return assemble_rows(package, (evaluate_single_point(package, index, values) for index in package.window.indices()))


def recover_points(ledger, samples, row_refs, targets):
    from processing.recovery import recover_points as _recover_points
    return _recover_points(ledger, samples, row_refs, targets)
