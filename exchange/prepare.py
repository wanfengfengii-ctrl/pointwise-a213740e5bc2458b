from uuid import uuid4

from exchange.manifest import WindowPackage, build_sample_manifest
from exchange.window import validate_window
from recipe.units import require_input_unit


def prepare_window(revisions, recipes, issues, revision, recipe_version, lo, hi):
    record = revisions.get_revision(revision)
    recipe = recipes.get_version(recipe_version)
    window = validate_window(record.length, lo, hi)
    require_input_unit(record.unit, recipe.units)
    required = build_sample_manifest(record.length, window, recipe.taps)
    package = WindowPackage(
        f'E-{uuid4().hex}', record.revision, record.length, recipe.version,
        recipe.units, window, recipe.taps, required,
    )
    issues.save(package)
    return package
