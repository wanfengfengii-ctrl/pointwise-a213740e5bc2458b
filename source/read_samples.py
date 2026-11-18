from source.sample_map import SparseSamples, validate_sample_index


def read_samples(store, revision, indices):
    record = store.get_revision(revision)
    try:
        indices = iter(indices)
    except TypeError as exc:
        raise ValueError('expected sample indices') from exc
    requested = sorted({validate_sample_index(index, record.length) for index in indices})
    return SparseSamples(revision, store.read_entries(revision, requested))
