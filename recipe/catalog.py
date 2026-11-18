from recipe.taps import normalize_taps
from recipe.units import RecipeUnits


def validate_recipe_name(name):
    if not isinstance(name, str) or not name or name != name.strip() or not name.isprintable():
        raise ValueError('invalid recipe name')
    return name


def register_recipe(store, name, input_unit, output_unit, taps):
    validate_recipe_name(name)
    units = RecipeUnits(input_unit, output_unit)
    weights = normalize_taps(taps)
    return store.save_version(name, units, weights)
