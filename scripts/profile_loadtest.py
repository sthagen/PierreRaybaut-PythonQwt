"""Profile the load test for issue #93 work.

Runs ``qwt.tests.test_loadtest`` under cProfile, dumps the cumulative-time
top-N functions plus a focused subset (qwt internals only).
"""

from __future__ import annotations

import cProfile
import os
import pstats
import sys
from io import StringIO


def main() -> int:
    os.environ["PYTHONQWT_UNATTENDED_TESTS"] = "1"

    # Import lazily so PYTHONQWT_UNATTENDED_TESTS is honored
    from qwt.tests import test_loadtest

    pr = cProfile.Profile()
    pr.enable()
    test_loadtest.test_loadtest()
    pr.disable()

    out_path = sys.argv[1] if len(sys.argv) > 1 else "profile.out"
    pr.dump_stats(out_path)

    buf = StringIO()
    stats = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    stats.print_stats(40)
    print(buf.getvalue())

    buf2 = StringIO()
    stats2 = pstats.Stats(pr, stream=buf2).sort_stats("tottime")
    stats2.print_stats(40)
    print("==== TOTTIME TOP 40 ====")
    print(buf2.getvalue())

    buf3 = StringIO()
    stats3 = pstats.Stats(pr, stream=buf3).sort_stats("tottime")
    stats3.print_stats(r"qwt[\\/].*", 40)
    print("==== TOTTIME (qwt only) ====")
    print(buf3.getvalue())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
