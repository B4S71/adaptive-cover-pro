"""Microbenchmark for the position-forecast hot path.

Originally written to validate the fix for issue #437 (forecast computing
on every state read, blocking the event loop). Kept as a regression guard
and a baseline for further forecast-perf work (see the perf-followup
issues filed off that PR).

Usage:

    venv/bin/python scripts/bench_forecast.py

The script imports `custom_components.adaptive_cover_pro` directly, so
running it against a different branch just requires `git checkout`. It
prints one section per measurement and a `BEFORE`/`AFTER` banner derived
from whether the `FORECAST_RECOMPUTE_INTERVAL_MIN` constant exists.
"""

from __future__ import annotations

import gc
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Resolve the repo root from this script's location so `git checkout` to
# another branch keeps imports working without editing the script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from astral import LocationInfo  # noqa: E402
from astral.location import Location  # noqa: E402

from custom_components.adaptive_cover_pro.forecast import build_forecast  # noqa: E402
from custom_components.adaptive_cover_pro.sun import SunData  # noqa: E402


class StubCover:
    """Mimic the two attributes `build_forecast` actually reads."""

    def __init__(self, azi: float, ele: float) -> None:
        """Capture sun angles; only `direct_sun_valid` ends up consumed."""
        self.direct_sun_valid = ele > 0

    def calculate_percentage(self) -> int:
        """Return a constant — the benchmark measures iteration cost, not math."""
        return 50


def cover_factory(azi: float, ele: float) -> StubCover:
    return StubCover(azi, ele)


def make_sun_data() -> SunData:
    info = LocationInfo("Paris", "France", "Europe/Paris", 48.8566, 2.3522)
    return SunData(timezone=info.timezone, location=Location(info), elevation=10.0)


def time_ms(fn, *args, **kwargs) -> tuple[float, object]:
    gc.collect()
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return (t1 - t0) * 1000.0, result


_TZ = ZoneInfo("Europe/Paris")
_NOW = datetime.now(tz=_TZ).replace(hour=10, minute=0, second=0, microsecond=0)


def measure_cold_sundata() -> None:
    print(
        "=== Measurement 1: Cold SunData property access (fresh instance each time) ==="
    )
    sd = make_sun_data()
    ms, _ = time_ms(lambda: sd.times)
    print(f"  sd.times (first read):          {ms:8.2f} ms")

    sd = make_sun_data()
    ms, _ = time_ms(lambda: sd.solar_azimuth)
    print(f"  sd.solar_azimuth (first read):  {ms:8.2f} ms")

    sd = make_sun_data()
    ms, _ = time_ms(lambda: sd.solar_elevation)
    print(f"  sd.solar_elevation (first):     {ms:8.2f} ms")


def measure_hot_sundata() -> None:
    print("\n=== Measurement 2: Hot SunData property re-access (same instance) ===")
    sd = make_sun_data()
    _ = sd.times  # prime
    _ = sd.solar_azimuth
    _ = sd.solar_elevation

    ms, _ = time_ms(lambda: sd.times)
    print(f"  sd.times (2nd read):            {ms:8.4f} ms")
    ms, _ = time_ms(lambda: sd.solar_azimuth)
    print(f"  sd.solar_azimuth (2nd):         {ms:8.4f} ms")
    ms, _ = time_ms(lambda: sd.solar_elevation)
    print(f"  sd.solar_elevation (2nd):       {ms:8.4f} ms")


def measure_build_forecast_repeated() -> None:
    print("\n=== Measurement 3: build_forecast — 5 calls on same SunData instance ===")
    sd = make_sun_data()
    times_ms: list[float] = []
    sample_count = 0
    for i in range(5):
        ms, fc = time_ms(
            build_forecast,
            sun_data=sd,
            cover_factory=cover_factory,
            default_position=50,
            now=_NOW,
        )
        times_ms.append(ms)
        sample_count = len(fc.samples)
        print(
            f"  Call {i + 1}:                       {ms:8.2f} ms  ({sample_count} samples)"
        )
    avg = sum(times_ms) / len(times_ms)
    print(f"  Mean:                           {avg:8.2f} ms / call")


def measure_boot_fanout_single_entry() -> None:
    print("\n=== Measurement 4: Boot fan-out — 28 build_forecast calls (1 entry) ===")
    print(
        "    Pre-fix observed cost: ~14 switches × 2 sensor reads = 28 calls per entry"
    )
    sd = make_sun_data()
    gc.collect()
    t0 = time.perf_counter()
    for _ in range(28):
        build_forecast(
            sun_data=sd,
            cover_factory=cover_factory,
            default_position=50,
            now=_NOW,
        )
    t1 = time.perf_counter()
    total_ms = (t1 - t0) * 1000.0
    print(f"  28 calls total:                 {total_ms:8.2f} ms")
    print(f"  Mean per call:                  {total_ms / 28:8.2f} ms")


def measure_boot_fanout_ten_entries() -> None:
    print("\n=== Measurement 5: Full boot — 10 entries × 28 calls = 280 calls ===")
    print(
        "    User reported: 10 ACP instances pushed past HA bootstrap stage 2 timeout"
    )
    sds = [make_sun_data() for _ in range(10)]
    gc.collect()
    t0 = time.perf_counter()
    for sd in sds:
        for _ in range(28):
            build_forecast(
                sun_data=sd,
                cover_factory=cover_factory,
                default_position=50,
                now=_NOW,
            )
    t1 = time.perf_counter()
    total_ms = (t1 - t0) * 1000.0
    print(
        f"  280 calls total:                {total_ms:8.2f} ms  ({total_ms / 1000:.2f} s)"
    )
    print(f"  Mean per call:                  {total_ms / 280:8.2f} ms")


def main() -> None:
    try:
        from custom_components.adaptive_cover_pro.const import (
            FORECAST_RECOMPUTE_INTERVAL_MIN,
        )

        banner = f"AFTER #437 (FORECAST_RECOMPUTE_INTERVAL_MIN = {FORECAST_RECOMPUTE_INTERVAL_MIN})"
    except ImportError:
        banner = "BEFORE #437 (no FORECAST_RECOMPUTE_INTERVAL_MIN const)"
    print(f"### Branch state: {banner}\n")

    measure_cold_sundata()
    measure_hot_sundata()
    measure_build_forecast_repeated()
    measure_boot_fanout_single_entry()
    measure_boot_fanout_ten_entries()


if __name__ == "__main__":
    main()
