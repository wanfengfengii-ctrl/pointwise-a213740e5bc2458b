import json

from exchange.manifest import WindowPackage, validate_package_manifest
from exchange.window import validate_window
from recipe.taps import decode_taps, encode_taps
from recipe.units import RecipeUnits


WINDOW_FORMAT_V1 = 1
_WINDOW_FIELDS = {
    'version', 'issue_id', 'revision', 'length', 'recipe_version', 'input_unit',
    'output_unit', 'window', 'taps', 'required_samples',
}


def encode_window(package):
    validate_package_manifest(package)
    document = {
        'version': WINDOW_FORMAT_V1,
        'issue_id': package.issue_id,
        'revision': package.revision,
        'length': package.length,
        'recipe_version': package.recipe_version,
        'input_unit': package.units.input_unit,
        'output_unit': package.units.output_unit,
        'window': [package.window.lo, package.window.hi],
        'taps': encode_taps(package.taps),
        'required_samples': list(package.required_samples),
    }
    return json.dumps(document, sort_keys=True, separators=(',', ':')).encode('utf-8')


def decode_window(payload):
    try:
        document = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid window JSON') from exc
    if not isinstance(document, dict) or document.keys() != _WINDOW_FIELDS:
        raise ValueError('invalid window package fields')
    if type(document['version']) is not int or document['version'] != WINDOW_FORMAT_V1:
        raise ValueError('unsupported window package version')
    bounds = document['window']
    required = document['required_samples']
    if not isinstance(bounds, list) or len(bounds) != 2 or not isinstance(required, list):
        raise ValueError('invalid window bounds or sample manifest')
    package = WindowPackage(
        document['issue_id'], document['revision'], document['length'], document['recipe_version'],
        RecipeUnits(document['input_unit'], document['output_unit']),
        validate_window(document['length'], *bounds), decode_taps(document['taps']), tuple(required),
    )
    validate_package_manifest(package)
    return package
