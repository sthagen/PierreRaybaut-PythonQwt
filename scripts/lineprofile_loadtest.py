"""Line-profile the hot functions identified by cProfile.

Run with the active Qt binding selected via QT_API.

Usage::

    python scripts/lineprofile_loadtest.py [funcname1 funcname2 ...]

If no function names are given, a default set of hotspots is profiled.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("PYTHONQWT_UNATTENDED_TESTS", "1")

from line_profiler import LineProfiler  # noqa: E402

import qwt.scale_div  # noqa: E402
import qwt.scale_draw  # noqa: E402
import qwt.scale_engine  # noqa: E402
import qwt.scale_map  # noqa: E402
import qwt.text  # noqa: E402
from qwt.tests import test_loadtest  # noqa: E402

# (module, qualified-name) — only methods listed here are line-profiled.
HOTSPOTS = {
    "textSize": qwt.text.QwtText.textSize,
    "textEngine": qwt.text.QwtText.textEngine,
    "QwtText.__init__": qwt.text.QwtText.__init__,
    "PlainTextEngine.textMargins": qwt.text.QwtPlainTextEngine.textMargins,
    "labelRect": qwt.scale_draw.QwtScaleDraw.labelRect,
    "labelPosition": qwt.scale_draw.QwtScaleDraw.labelPosition,
    "labelTransformation": qwt.scale_draw.QwtScaleDraw.labelTransformation,
    "getBorderDistHint": qwt.scale_draw.QwtScaleDraw.getBorderDistHint,
    "draw": qwt.scale_draw.QwtScaleDraw.draw,
    "drawLabel": qwt.scale_draw.QwtScaleDraw.drawLabel,
    "drawTick": qwt.scale_draw.QwtScaleDraw.drawTick,
    "drawBackbone": qwt.scale_draw.QwtScaleDraw.drawBackbone,
    "scale_map.transform": qwt.scale_map.QwtScaleMap.transform,
    "scale_engine.strip": qwt.scale_engine.QwtScaleEngine.strip,
    "scale_engine.contains": qwt.scale_engine.QwtScaleEngine.contains,
    "scale_div.contains": qwt.scale_div.QwtScaleDiv.contains,
    "orientation": qwt.scale_draw.QwtScaleDraw.orientation,
}


def main() -> None:
    selected = sys.argv[1:] or list(HOTSPOTS)
    profiler = LineProfiler()
    for name in selected:
        if name not in HOTSPOTS:
            print(f"Unknown hotspot: {name!r}", file=sys.stderr)
            continue
        profiler.add_function(HOTSPOTS[name])

    profiler.runcall(test_loadtest.test_loadtest)
    profiler.print_stats(stream=sys.stdout, output_unit=1e-6)


if __name__ == "__main__":
    main()
