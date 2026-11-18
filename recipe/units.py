from dataclasses import dataclass


def validate_unit(unit):
    if (not isinstance(unit, str) or not unit or not unit.isprintable()
            or any(character.isspace() for character in unit)):
        raise ValueError('invalid unit identifier')
    return unit


@dataclass(frozen=True)
class RecipeUnits:
    input_unit: str
    output_unit: str

    def __post_init__(self):
        validate_unit(self.input_unit)
        validate_unit(self.output_unit)


def require_input_unit(record_unit, recipe_units):
    if record_unit != recipe_units.input_unit:
        raise ValueError(f'record unit {record_unit!r} differs from recipe input {recipe_units.input_unit!r}')
