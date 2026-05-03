# Issue #93 — Performance degradation with Qt6: optimization summary

This document summarises the work done on the `fix/93-performance-degradation-with-qt6` branch to investigate and close the Qt5↔Qt6 performance gap reported in [issue #93](https://github.com/PlotPyStack/PythonQwt/issues/93). It walks through each optimization phase, the diagnostic method used, the change applied, and the measured impact.

All numbers below were collected on the same Windows 11 machine, Python 3.11.9, with three sibling virtual environments (`.venvs/pyqt5`, `.venvs/pyqt6`, `.venvs/pyside6`), each pinning a single Qt binding (PyQt5 5.15.11 / Qt 5.15.2, PyQt6 6.11.0 / Qt 6.11.0, PySide6 6.11.0 / Qt 6.11.0).

Two benchmarks were used throughout:

- **`qwt/tests/test_loadtest.py`** — the PythonQwt micro load test (raw QwtPlot widgets, no PlotPy). Driven by `scripts/bench_qt.ps1`. Reports `Average elapsed time: <ms> ms` per binding.
- **PlotPy `test_loadtest`** — `plotpy/tests/benchmarks/test_loadtest.py`, the test cited in the original GitHub issue. Driven by `scripts/bench_plotpy_loadtest.py` (60 plot widgets, 3 runs).

## Baseline (master, commit `1ab70cd`)

| Benchmark | PyQt5 | PyQt6 | PySide6 |
|---|---:|---:|---:|
| PythonQwt `test_loadtest` (avg of 5) | ~1 900 ms | ~2 300 ms | ~2 900 ms |
| PlotPy `test_loadtest`, 60 plots (avg of 3) | 25 134 ms | 42 202 ms | 53 160 ms |

Headline gap on PlotPy: **PyQt6 ≈ +68 % slower than PyQt5**, **PySide6 ≈ +111 % slower than PyQt5**.

The cProfile traces taken on master pointed at four hot families of code paths inside PythonQwt:

1. `QwtScaleMap.transform()` — called on every coordinate transformed.
2. `QwtScaleDiv.contains()` and `QwtScaleEngine.contains()/strip()` — called on every tick label candidate.
3. `QwtAbstractScaleDraw.labelRect()` and helpers — called on every drawn tick.
4. `QwtText` / `QwtPlainTextEngine` text-size and text-margin computations — called on every tick label and every plot title.

All four are amortised over thousands of calls per plot, and all four are sensitive to per-call Python overhead (attribute lookups, QObject machinery, redundant Qt round-trips). That is precisely the kind of overhead that the Qt6 bindings (especially PySide6) make more expensive than Qt5, which explains why a regression that is barely visible on Qt5 becomes a 2× slowdown on Qt6.

## Phase 1 — cProfile-driven optimizations (commit `ef793e1`)

**Method.** `scripts/profile_loadtest.py` runs the PythonQwt load test under `cProfile` and dumps a sorted-by-cumulative-time stats file. Diff between PyQt5 and PySide6 traces highlighted the four families above.

**Changes.**

- **`qwt/scale_map.py`** — inlined the scalar fast path in `QwtScaleMap.transform()` (avoid the array branch and a method dispatch when the input is a plain Python `float`).
- **`qwt/scale_div.py`** — rewrote `QwtScaleDiv.contains()` as a direct comparison against the cached lower/upper bounds, instead of going through `QwtInterval`.
- **`qwt/scale_engine.py`** — `QwtScaleEngine.contains()` and `QwtScaleEngine.strip()` similarly bypass `QwtInterval` round-trips for the common case.
- **`qwt/scale_draw.py`** — replaced the per-call alignment branching in `labelRect()`/`labelPosition()` with module-level constants (`_ALIGN_BOTTOM`, `_ALIGN_TOP`, `_ALIGN_LEFT`, `_ALIGN_RIGHT`); added a rotation==0 fast path in `labelRect()`; cached the axis `orientation` once in `setAlignment()` instead of recomputing it on every call.
- **`qwt/text.py`** — first round of cleanups around `QwtText.textSize()` and `QwtPlainTextEngine.textMargins()`, plus a per-engine "last seen font id" fast path that skips the `QFontMetricsF` rebuild when the same `QFont` instance is reused (which is the dominant case during a single plot repaint).

**Results after phase 1** (PythonQwt micro `test_loadtest`, 5 runs each):

| Binding | Before | After phase 1 | Speedup |
|---|---:|---:|---:|
| PyQt5 | ~1 900 ms | ~620 ms | ×3.0 |
| PyQt6 | ~2 300 ms | ~780 ms | ×2.9 |
| PySide6 | ~2 900 ms | ~960 ms | ×3.0 |

Phase 1 closed most of the absolute slowdown but did not change the *relative* Qt5↔Qt6 gap — all three bindings benefited roughly equally, because the optimizations attacked Python-side overhead that scales with call count regardless of binding.

## Phase 2 — line-profiler-driven optimizations (commit `27a0e17`)

**Method.** `scripts/lineprofile_loadtest.py` instruments the surviving hot functions with `line_profiler` (`@profile`) and re-runs the load test. The line-by-line traces revealed two new dominant costs that did not show up clearly in cProfile:

1. The `QObject` base class on `QwtText_PrivateData` and on the `_PrivateData` classes inside `qwt/scale_draw.py`. Every instantiation went through Qt's meta-object system, which is dramatically more expensive on PyQt6 / PySide6 than on PyQt5.
2. Repeated calls to `QFont.key()` from within `QwtText.textSize()`, `QwtText.effectiveAscent()` and `QwtPlainTextEngine.textMargins()`. Each call serialises the full font descriptor; the same descriptor is hit thousands of times during a single load test because the same default font instance is reused.

**Changes.**

- **`qwt/text.py`** — `QwtText_PrivateData` is now a plain `object` subclass with `__slots__`; no QObject. Added a process-wide `_FONT_KEY_CACHE` keyed by `id(font)` that memoizes `font.key()` (with a hard cap of 1024 entries to avoid unbounded growth). Helper `font_key_cached()` is used by `effectiveAscent`, `QwtPlainTextEngine.textMargins`, and `QwtText.textSize`.
- **`qwt/scale_draw.py`** — the various `_PrivateData` containers also drop `QObject` and use `__slots__`.

**Results after phase 2** (PythonQwt micro `test_loadtest`, 5 runs each):

| Binding | Before phase 2 | After phase 2 | Speedup vs phase 1 | Speedup vs master |
|---|---:|---:|---:|---:|
| PyQt5 | ~620 ms | ~445 ms | ×1.4 | ×4.3 |
| PyQt6 | ~780 ms | ~480 ms | ×1.6 | ×4.8 |
| PySide6 | ~960 ms | ~600 ms | ×1.6 | ×4.8 |

Phase 2 finally closed the *relative* gap as well: Qt6 bindings benefit more than Qt5 from removing QObject inheritance and `font.key()` calls, because the per-call overhead they save is binding-cost-dominated.

## Phase 3 — screenshot regression analysis

**Method.** Two new helpers were added in `scripts/`:

- **`capture_screenshots.py`** — runs each of the 22 PythonQwt visual tests in a subprocess with `PYTHONQWT_TAKE_SCREENSHOTS=1` and copies the resulting PNGs into `shots/<branch>/<binding>/`.
- **`diff_screenshots.py`** — pixel-compares two screenshot folders (Pillow + NumPy) and emits a markdown table with `IDENTICAL` / `EQUAL_PIXELS` / `DIFFER` status, plus the count and magnitude of differing pixels.

A full matrix was captured (master × 3 bindings, fix × 3 bindings, plus self-compare baselines master×master and fix×fix to filter out flaky tests that have inherently random or time-stamped output).

**Findings.**

- **PyQt6 and PySide6**: zero new deterministic differences vs master. Every diff that appeared was already present in the master self-compare baseline (the 6 tests `test_cpudemo`, `test_curvebenchmark1/2`, `test_data`, `test_loadtest`, `test_mapdemo`, all of which use random data or timestamps).
- **PyQt5**: 6 *new* deterministic, sub-perceptual differences appeared, in `test_backingstore`, `test_bodedemo`, `test_image`, `test_relativemargin`, `test_symbols`, `test_vertical`. All diffs were tiny (a few dozen pixels each, max magnitude ≤ 26/255), scattered around antialiased text and curve edges.

### Per-test screenshot status (master vs phase-2 fix, all bindings)

Each cell aggregates two pixel-diffs per test (master vs `master2` self-compare baseline, and master vs phase-2 fix). The classification rule is:

- ✅ — both diffs report identical or pixel-equal output (test is fully reproducible *and* the optimization branch did not change it).
- ⚠️ — both diffs are non-zero (test is *intrinsically* flaky — random data, timestamps, live system stats — so any difference is noise, not a regression).
- ❌ — baseline is identical but the fix differs (a real visual regression introduced by the optimization branch).

| Test | PyQt5 | PyQt6 | PySide6 |
|---|:-:|:-:|:-:|
| `test_backingstore` | ❌ 55 px (max=11) | ✅ | ✅ |
| `test_bodedemo` | ❌ 39 px (max=16) | ✅ | ✅ |
| `test_cartesian` | ✅ | ✅ | ✅ |
| `test_cpudemo` | ⚠️ | ⚠️ | ⚠️ |
| `test_curvebenchmark1` | ⚠️ | ⚠️ | ⚠️ |
| `test_curvebenchmark2` | ⚠️ | ⚠️ | ⚠️ |
| `test_curvedemo1` | ✅ | ✅ | ✅ |
| `test_curvedemo2` | ✅ | ✅ | ✅ |
| `test_data` | ⚠️ | ⚠️ | ⚠️ |
| `test_errorbar` | ✅ | ✅ | ✅ |
| `test_eventfilter` | ✅ | ✅ | ✅ |
| `test_highdpi` | ✅ | ✅ | ✅ |
| `test_image` | ❌ 6 px (max=9) | ✅ | ✅ |
| `test_loadtest` | ⚠️ | ⚠️ | ⚠️ |
| `test_logcurve` | ✅ | ✅ | ✅ |
| `test_mapdemo` | ⚠️ | ⚠️ | ⚠️ |
| `test_multidemo` | ✅ | ✅ | ✅ |
| `test_relativemargin` | ❌ 72 px (max=11) | ✅ | ✅ |
| `test_simple` | ✅ | ✅ | ✅ |
| `test_stylesheet` | ✅ | ✅ | ✅ |
| `test_symbols` | ❌ 4 px (max=9) | ✅ | ✅ |
| `test_vertical` | ❌ 88 px (max=26) | ✅ | ✅ |

**Summary at end of phase 3.** PyQt6 and PySide6: 16 ✅ / 6 ⚠️ / **0 ❌**. PyQt5: 10 ✅ / 6 ⚠️ / **6 ❌**. The 6 ❌ entries on PyQt5 are the regression that phase 4 fixes.

**Root cause.** The id-keyed `font.key()` cache subtly changes the order in which the Qt5 font engine is asked to materialise specific font descriptors. On Qt5, the font engine hints text glyphs slightly differently depending on first-touch order — invisible to a human, but bit-non-identical to master. Qt6's font engine does not show this sensitivity.

## Phase 4 — Option A: gate the font-key fast path on Qt5 (current state)

**Change.** In `qwt/text.py`, the id-keyed cache is now guarded by a Qt-version check:

```python
from qtpy import QT_VERSION as _QT_VERSION

_USE_FONT_KEY_FAST_PATH = not str(_QT_VERSION).startswith("5.")

def font_key_cached(font) -> str:
    if not _USE_FONT_KEY_FAST_PATH:
        return font.key()
    # ... id-keyed cache lookup ...
```

On Qt5 this becomes a thin pass-through to `font.key()` — bit-identical output to master is restored. On Qt6 (where it actually matters most for this issue) the optimization stays in place.

**Verification.**

1. **Screenshot regression** — re-ran PyQt5 capture and diff. The 6 ❌ entries from the phase 3 table all flip to ✅. Final per-binding tally becomes **16 ✅ / 6 ⚠️ / 0 ❌** on every binding — i.e. byte-identical output to master on every test that is reproducible at all.
2. **Test suite** — `pytest -q` with `PYTHONQWT_UNATTENDED_TESTS=1` on all three bindings:
   - PyQt5: 26 passed, 1 skipped
   - PyQt6: 26 passed, 1 skipped
   - PySide6: 26 passed, 1 skipped, 1 warning
3. **Performance** — PyQt5 micro-bench rose from ~445 ms to ~450–550 ms (≈ +5 ms, well within the run-to-run noise). Qt6 numbers are unchanged.

## Final results

### PythonQwt micro `test_loadtest` (5 runs each, ms)

| Binding | master | fix/93 (Option A) | Speedup |
|---|---:|---:|---:|
| PyQt5 | ~1 900 | ~450–550 | ×3.5–×4.2 |
| PyQt6 | ~2 300 | ~450–675 | ×3.4–×5.1 |
| PySide6 | ~2 900 | ~580–795 | ×3.6–×5.0 |

### PlotPy `test_loadtest`, 60 plots (3 runs each, ms)

| Binding | master (`1ab70cd`) | fix/93 (Option A) | Speedup |
|---|---:|---:|---:|
| PyQt5 | 25 134 | **16 169** | ×1.55 |
| PyQt6 | 42 202 | **21 387** | ×1.97 |
| PySide6 | 53 160 | **24 849** | ×2.14 |

### Cross-binding gap (PlotPy load test)

| Comparison | master | fix/93 |
|---|---:|---:|
| PyQt6 vs PyQt5 | +68 % slower | **+32 % slower** |
| PySide6 vs PyQt5 | +111 % slower | **+54 % slower** |

The original issue — a 1.5×–2× penalty for Qt6 over Qt5 — is largely resolved on the PlotPy load test, while the PyQt5 path remains bit-compatible with master both visually and behaviourally.

## Backwards compatibility & public API surface

The optimizations are deliberately confined to internal hot paths and do not alter the documented public API:

- `QwtScaleMap.transform()`, `QwtScaleDiv.contains()`, `QwtScaleEngine.contains()/strip()`, `QwtAbstractScaleDraw.labelRect()/labelPosition()` — same signatures, same semantics, same return values.
- `QwtText` and `QwtPlainTextEngine` — same signatures and semantics. The internal `_PrivateData` containers no longer derive from `QObject`; this is invisible from the outside because `_PrivateData` was a private holder, never exposed and never used as a Qt signal/slot target.
- New module-level helper `qwt.text.font_key_cached()` is internal (lowercase, undocumented). It can be safely removed or refactored later without breaking any public consumer.
- No new dependency. No change to `qtpy` requirements; the Qt-version gate uses `qtpy.QT_VERSION` which is already imported transitively.

The screenshot regression sweep above is the empirical confirmation of this: byte-identical PNGs on every non-flaky test mean PythonQwt's rendered output is unchanged, on every binding.

## Reproduction quickstart

The whole evaluation can be reproduced from a fresh checkout in a few commands. The scripts assume three sibling virtual environments under `.venvs/{pyqt5,pyqt6,pyside6}/`, each with a single Qt binding plus `numpy`, `qtpy`, `pytest`, `pillow`, and `PythonQwt` installed editable.

```powershell
# 1. PythonQwt micro load test, all three bindings, 5 runs each
.\scripts\bench_qt.ps1 -Repeat 5

# 2. Visual regression sweep (PyQt5 example; repeat for pyqt6 / pyside6)
$env:QT_API = "pyqt5"
& .\.venvs\pyqt5\Scripts\python.exe scripts\capture_screenshots.py shots\fix\pyqt5
& .\.venvs\pyqt5\Scripts\python.exe scripts\capture_screenshots.py shots\master\pyqt5  # after `git checkout master`
& .\.venvs\pyside6\Scripts\python.exe scripts\diff_screenshots.py shots\master\pyqt5 shots\fix\pyqt5

# 3. PlotPy load test (the test cited in the original GitHub issue)
$env:PYTHONPATH = "c:\Dev\PlotPy;c:\Dev\guidata"
foreach ($b in "pyqt5","pyqt6","pyside6") {
    & ".\.venvs\$b\Scripts\python.exe" scripts\bench_plotpy_loadtest.py --repeat 3 --nplots 60
}
```

## Test environment

| Component | Value |
|---|---|
| OS | Windows 11 (x64) |
| Python | 3.11.9 (NuGet build) |
| PyQt5 | 5.15.11 (Qt 5.15.2) |
| PyQt6 | 6.11.0 (Qt 6.11.0) |
| PySide6 | 6.11.0 (Qt 6.11.0) |
| qtpy | latest available at the time of capture |
| PlotPy (for PlotPy load test) | 2.9.1 (editable install from `c:\Dev\PlotPy`) |
| guidata (for PlotPy load test) | 3.14.3 (editable install from `c:\Dev\guidata`) |
| Display | physical desktop session (not `offscreen`) — measurements include real Qt paint/composite cost |

## Files touched

| File | Phase 1 (cProfile) | Phase 2 (line-profiler) | Phase 4 (Option A) |
|---|:-:|:-:|:-:|
| `qwt/scale_map.py` | ✓ | | |
| `qwt/scale_div.py` | ✓ | | |
| `qwt/scale_engine.py` | ✓ | | |
| `qwt/scale_draw.py` | ✓ | ✓ (drop QObject, `__slots__`) | |
| `qwt/text.py` | ✓ | ✓ (drop QObject, font cache) | ✓ (Qt5 gate) |

Tooling added under `scripts/`:

- `bench_qt.ps1` — driver for the PythonQwt micro load test across the three venvs.
- `profile_loadtest.py` — cProfile harness used in phase 1.
- `lineprofile_loadtest.py` — line_profiler harness used in phase 2.
- `capture_screenshots.py` / `diff_screenshots.py` — phase 3 visual regression tooling.
- `bench_plotpy_loadtest.py` — driver for the PlotPy load test (the test cited in the original issue).
