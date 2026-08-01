#!/usr/bin/env python3
"""Run every suite: python3 tests/run.py"""
import sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if __name__ == "__main__":
    suite = unittest.TestLoader().discover(str(HERE), pattern="test_*.py")
    sys.exit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
