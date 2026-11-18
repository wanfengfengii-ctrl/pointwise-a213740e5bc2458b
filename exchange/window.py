from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    lo: int
    hi: int

    def indices(self):
        return range(self.lo, self.hi)


def validate_window(length, lo, hi):
    if type(length) is not int or length <= 0:
        raise ValueError('invalid record length')
    if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= length:
        raise ValueError('invalid output window')
    return Window(lo, hi)


def is_record_index(index, length):
    return 0 <= index < length
