from recipe.units import validate_unit
from source.sample_map import normalize_samples
from source.wave_format import decode_wave_file


def import_revision(store, source, length, unit, samples, base_revision=None):
    if not isinstance(source, str) or not source or source != source.strip() or not source.isprintable():
        raise ValueError('invalid source identifier')
    if type(length) is not int or length <= 0:
        raise ValueError('record length must be a positive integer')
    validate_unit(unit)
    if base_revision is not None and (not isinstance(base_revision, str) or not base_revision.strip()):
        raise ValueError('invalid base revision identifier')
    normalized = normalize_samples(samples, length)
    return store.save_revision(source, length, unit, normalized, base_revision)


def import_wave_file(store, path):
    wave = decode_wave_file(path)
    return import_revision(store, wave.source, wave.length, wave.unit, wave.samples, wave.base_revision)
