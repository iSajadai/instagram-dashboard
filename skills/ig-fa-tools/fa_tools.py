#!/usr/bin/env python3
"""Persian Instagram tools for the ig-*-fa Claude skills: hook scores, beat timing, the caption linter,
the humanizer, swipe ranking, the 26 formulas and the profile rubric. Standard library only.
Built from sajadai/fa by `python -m sajadai build-skills`; edit it there, not here."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fa.cli import main  # noqa: E402

main()
