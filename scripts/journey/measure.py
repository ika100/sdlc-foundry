"""Forwarder (spec 181): the measurement is `cplat platform runs journey measure`; this script keeps the old entry point.

  python3 scripts/journey/measure.py <session>[,<session>...] <start> <end> <owner/repo>... [--steps FILE] [--json]
                                     [--journey RUN_ID] [--records FILE]

Same arguments, same output, same exit code. See scripts/cplat/journey_measure.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cplat"))

import core  # noqa: E402
import journey_measure  # noqa: E402

if __name__ == "__main__":
    try:
        code = journey_measure.main(sys.argv[1:])
    except core.PlatformError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if e.hint:
            print(f"  fix: {e.hint}", file=sys.stderr)
        code = 1
    sys.exit(code)
