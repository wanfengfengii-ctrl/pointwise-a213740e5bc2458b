from source.sample_map import SparseSamples, validate_sample_index


def bind_samples(package, samples):
    if not isinstance(samples, SparseSamples) or samples.revision != package.revision:
        raise ValueError('sample revision does not match the window')
    for index in samples.samples:
        validate_sample_index(index, package.length)
    return samples.samples
