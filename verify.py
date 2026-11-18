import unittest
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'), top_level_dir=str(root))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1
    from check_recovery_chain import main as check_recovery
    return check_recovery()


if __name__ == '__main__':
    raise SystemExit(main())
