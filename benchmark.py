from __future__ import annotations

import ast
import hashlib
import math
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# =============================================================================
# FIBONACCI HISTORICAL RUNNER
# BUILD: historical-v2.0 / 2026-09-01
#
# This runner benchmarks the ACTUAL project progression:
#   V1 -> fibv1.py   Python iterative
#   V2 -> fibv2.py   Python recursive fast doubling
#   V3 -> fibv3.py   Python iterative/binary fast doubling
#   V4 -> fibv4.exe  C++ + GMP recursive fast doubling
#
# The Python files are NOT imported normally because the historical copies have
# interactive input()/print() code at module scope. Instead, this runner parses
# each file and loads only the requested function definition + imports.
# =============================================================================

RUNNER_BUILD = "historical-v2.0-2026-09-01"

FAST_CENTER = 0.90
FAST_LOW = 0.85
FAST_HIGH = 0.95

ACCURATE_CENTER = 0.995
ACCURATE_LOW = 0.99
ACCURATE_HIGH = 1.00

FAST_MAX_TUNE_STEPS = 8
ACCURATE_MAX_TUNE_STEPS = 10
ACCURATE_TUNE_REPS = 3
ACCURATE_FINAL_REPS = 7
ACCURATE_MAX_CERTIFY_ROUNDS = 5


@dataclass
class Version:
    key: str
    label: str
    measure_once: Callable[[int], float]


@dataclass
class Sample:
    n: int
    values: list[float]

    @property
    def median(self) -> float:
        return statistics.median(self.values)

    @property
    def low(self) -> float:
        return min(self.values)

    @property
    def high(self) -> float:
        return max(self.values)


@dataclass
class Result:
    version: Version
    sample: Sample
    target: float
    status: str
    bench_wall: float
    timed_runs: int

    @property
    def pct(self) -> float:
        return 100.0 * self.sample.median / self.target


# =============================================================================
# Historical source loading
# =============================================================================

def short_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def load_function_from_historical_file(path: Path, function_name: str) -> Callable:
    """Load a function without executing historical top-level prompts.

    We keep imports and the requested function definition. The function body is
    compiled directly from the user's source file; it is not rewritten here.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path.name} next to this runner")

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    body: list[ast.stmt] = []
    found = False

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            body.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            body.append(node)
            found = True

    if not found:
        raise RuntimeError(f"{path.name} does not define {function_name}()")

    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)

    ns: dict[str, object] = {
        "__name__": f"_historical_{path.stem}",
        "__file__": str(path),
    }
    exec(compile(module, str(path), "exec"), ns, ns)

    fn = ns.get(function_name)
    if not callable(fn):
        raise RuntimeError(f"Failed to load {function_name}() from {path.name}")
    return fn


def time_python(fn: Callable[[int], object], n: int) -> float:
    """Time only the Fibonacci function call with the highest-res Python clock."""
    start = time.perf_counter_ns()
    result = fn(n)
    elapsed = time.perf_counter_ns() - start

    # Touch the result outside the timed section so the work remains observable.
    if isinstance(result, tuple):
        result = result[0]
    if result is None:
        raise RuntimeError("Fibonacci implementation returned None")

    return elapsed / 1_000_000_000.0


def find_v4_executable(root: Path) -> Path:
    for name in ("fibv4.exe", "fibv4"):
        p = root / name
        if p.is_file():
            return p.resolve()
    raise FileNotFoundError(
        "Could not find fibv4.exe. Compile it first:\n"
        "g++ fibv4.cpp -O3 -std=c++17 -o fibv4.exe -lgmpxx -lgmp"
    )


def make_v4_timer(exe: Path) -> Callable[[int], float]:
    def measure(n: int) -> float:
        # V4 measures fib_pair(n) INSIDE C++. Process startup is outside the
        # reported score, so Python-vs-C++ is not polluted by launch overhead.
        cp = subprocess.run(
            [str(exe), "--bench", str(int(n)), "1"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )

        for line in reversed(cp.stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                value = float(line)
            except ValueError:
                continue
            if not math.isfinite(value) or value < 0:
                raise RuntimeError(f"Invalid V4 timing: {line!r}")
            return value

        raise RuntimeError(
            "Could not parse V4 timing output. fibv4.exe must support:\n"
            "  fibv4.exe --bench <n> 1\n"
            f"stdout was:\n{cp.stdout}"
        )

    return measure


def load_versions(root: Path) -> list[Version]:
    p1 = root / "fibv1.py"
    p2 = root / "fibv2.py"
    p3 = root / "fibv3.py"

    f1 = load_function_from_historical_file(p1, "fib_v1")
    f2 = load_function_from_historical_file(p2, "fib_pair")
    f3 = load_function_from_historical_file(p3, "fib_fast")
    v4exe = find_v4_executable(root)

    print(f"Runner build : {RUNNER_BUILD}")
    print(f"Loaded V1    : fibv1.py  sha256 {short_sha256(p1)}")
    print(f"Loaded V2    : fibv2.py  sha256 {short_sha256(p2)}")
    print(f"Loaded V3    : fibv3.py  sha256 {short_sha256(p3)}")
    print(f"Loaded V4    : {v4exe.name}")

    return [
        Version("v1", "V1 Python iterative", lambda n: time_python(f1, n)),
        Version("v2", "V2 Python recursive doubling", lambda n: time_python(f2, n)),
        Version("v3", "V3 Python iterative doubling", lambda n: time_python(f3, n)),
        Version("v4", "V4 C++/GMP doubling", make_v4_timer(v4exe)),
    ]


# =============================================================================
# Measurement helpers
# =============================================================================

def measure(v: Version, n: int, reps: int) -> Sample:
    n = max(1, int(n))
    reps = max(1, int(reps))
    return Sample(n=n, values=[v.measure_once(n) for _ in range(reps)])


def estimate_exponent(history: list[Sample]) -> float:
    """Estimate local t ~= C*n^p from recent measured points.

    This is used only to choose the NEXT candidate n. The reported score always
    comes from real measured runs, never from the model.
    """
    # Keep the most recent unique positive points.
    unique: dict[int, float] = {}
    for s in history[-8:]:
        if s.n > 1 and s.median > 0:
            unique[s.n] = s.median

    points = sorted(unique.items())[-5:]
    if len(points) < 2:
        return 1.6

    xs = [math.log(float(n)) for n, _ in points]
    ys = [math.log(t) for _, t in points]
    xbar = statistics.fmean(xs)
    ybar = statistics.fmean(ys)

    den = sum((x - xbar) ** 2 for x in xs)
    if den <= 1e-12:
        return 1.6

    p = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / den
    if not math.isfinite(p):
        return 1.6
    return max(0.6, min(3.5, p))


def next_n_from_measurement(
    current: Sample,
    desired_time: float,
    history: list[Sample],
    *,
    close: bool,
) -> int:
    if current.median <= 0:
        return max(current.n + 1, current.n * 2)

    p = estimate_exponent(history)
    factor = (desired_time / current.median) ** (1.0 / p)

    if close:
        factor = max(0.88, min(1.12, factor))
    else:
        factor = max(0.35, min(3.0, factor))

    guess = max(1, int(round(current.n * factor)))
    if guess == current.n:
        guess += 1 if current.median < desired_time else -1
    return max(1, guess)


def coarse_seed(v: Version, desired_time: float, seed: Optional[int] = None) -> tuple[Sample, list[Sample], int]:
    """Get into the neighborhood quickly using cheap single measurements."""
    history: list[Sample] = []
    timed_runs = 0

    n = max(32, int(seed or 1024))

    for _ in range(14):
        s = measure(v, n, 1)
        timed_runs += 1
        history.append(s)

        ratio = s.median / desired_time if desired_time > 0 else 1.0
        if 0.45 <= ratio <= 1.65:
            return s, history, timed_runs

        if ratio < 0.01:
            factor = 8.0
        elif ratio < 0.05:
            factor = 4.0
        elif ratio < 0.20:
            factor = 2.2
        elif ratio < 0.45:
            factor = 1.5
        else:
            # We overshot. Use the local model to come back down.
            p = estimate_exponent(history)
            factor = (desired_time / max(s.median, 1e-12)) ** (1.0 / p)
            factor = max(0.25, min(0.80, factor))

        n2 = max(1, int(round(n * factor)))
        if n2 == n:
            n2 += 1 if ratio < 1 else -1
        n = max(1, n2)

    return history[-1], history, timed_runs


# =============================================================================
# FAST MODE: approximately 90% with very little ceremony
# =============================================================================

def fast_search(v: Version, target: float, seed: Optional[int] = None) -> Result:
    wall0 = time.perf_counter()
    desired = FAST_CENTER * target

    cur, history, timed_runs = coarse_seed(v, desired, seed)
    best = cur

    for _ in range(FAST_MAX_TUNE_STEPS):
        pct = cur.median / target
        if FAST_LOW <= pct <= FAST_HIGH:
            best = cur
            break

        if abs(cur.median - desired) < abs(best.median - desired):
            best = cur

        n2 = next_n_from_measurement(
            cur,
            desired,
            history,
            close=(0.65 * target <= cur.median <= 1.15 * target),
        )
        cur = measure(v, n2, 1)
        timed_runs += 1
        history.append(cur)
    else:
        if abs(cur.median - desired) < abs(best.median - desired):
            best = cur

    # One fresh measurement at the selected n. If it is a huge scheduler
    # outlier, keep the calibration measurement rather than pretending the
    # implementation itself changed by 30% in one instant.
    fresh = measure(v, best.n, 1)
    timed_runs += 1
    if 0.70 * target <= fresh.median <= 1.10 * target:
        best = fresh

    # If the single verification lands outside the requested Fast band, spend
    # only two extra runs to reject a one-off scheduler spike/dip. Fast stays
    # cheap in the common case but is much less likely to report 80% or 105%.
    if not (FAST_LOW * target <= best.median <= FAST_HIGH * target):
        verify = measure(v, best.n, 3)
        timed_runs += 3
        history.append(verify)
        if abs(verify.median - desired) < abs(best.median - desired):
            best = verify

        # One last cheap correction only when Fast is still outside its band.
        if not (FAST_LOW * target <= best.median <= FAST_HIGH * target):
            n2 = next_n_from_measurement(best, desired, history, close=True)
            corrected = measure(v, n2, 1)
            timed_runs += 1
            if abs(corrected.median - desired) < abs(best.median - desired):
                best = corrected

    pct = best.median / target
    status = "OK" if FAST_LOW <= pct <= FAST_HIGH else "~"
    return Result(v, best, target, status, time.perf_counter() - wall0, timed_runs)


# =============================================================================
# ACCURATE MODE: real measured median must land in 99-100%
# =============================================================================

def accurate_search(v: Version, target: float, seed: Optional[int] = None) -> Result:
    wall0 = time.perf_counter()
    desired = ACCURATE_CENTER * target

    # If Both mode gave us a ~90% result, start a little above it.
    start_seed = max(1, int(seed * 1.06)) if seed else None
    cur, history, timed_runs = coarse_seed(v, desired, start_seed)

    # Tuning phase: median-of-3 near the target. We are NOT searching for an
    # exact integer cutoff. We are finding a real n whose measured median uses
    # 99-100% of the requested budget.
    best_under: Optional[Sample] = None

    for _ in range(ACCURATE_MAX_TUNE_STEPS):
        cur = measure(v, cur.n, ACCURATE_TUNE_REPS)
        timed_runs += ACCURATE_TUNE_REPS
        history.append(cur)

        if cur.median <= target:
            if best_under is None or cur.median > best_under.median:
                best_under = cur

        if ACCURATE_LOW * target <= cur.median <= target:
            break

        n2 = next_n_from_measurement(cur, desired, history, close=True)
        cur = Sample(n=n2, values=[v.measure_once(n2)])
        timed_runs += 1
        history.append(cur)

    candidate = cur if cur.median <= target else (best_under or cur)

    # Certification phase: median-of-7. If certification shifts out of the
    # 99-100% band, feed the REAL measured median back into the controller and
    # try again. An over-target median is never accepted as OK.
    final = candidate

    for _ in range(ACCURATE_MAX_CERTIFY_ROUNDS):
        final = measure(v, candidate.n, ACCURATE_FINAL_REPS)
        timed_runs += ACCURATE_FINAL_REPS
        history.append(final)

        if ACCURATE_LOW * target <= final.median <= target:
            return Result(v, final, target, "OK", time.perf_counter() - wall0, timed_runs)

        if final.median <= target:
            if best_under is None or final.median > best_under.median:
                best_under = final

        n2 = next_n_from_measurement(final, desired, history, close=True)

        # If a noisy over-target sample asks for a microscopic move, force at
        # least a small meaningful change in n.
        if n2 == candidate.n:
            delta = max(1, candidate.n // 2000)  # 0.05%
            n2 = candidate.n - delta if final.median > target else candidate.n + delta

        candidate = Sample(n=max(1, n2), values=[v.measure_once(max(1, n2))])
        timed_runs += 1
        history.append(candidate)

    # Last honest report. Prefer the closest certified-under sample, but do not
    # falsely label it accurate if the median misses 99-100%.
    if best_under is not None:
        final = measure(v, best_under.n, ACCURATE_FINAL_REPS)
        timed_runs += ACCURATE_FINAL_REPS

    status = "OK" if ACCURATE_LOW * target <= final.median <= target else "UNSTABLE"
    return Result(v, final, target, status, time.perf_counter() - wall0, timed_runs)


# =============================================================================
# Verification + reporting
# =============================================================================

def preflight(root: Path, versions: list[Version]) -> None:
    f1 = load_function_from_historical_file(root / "fibv1.py", "fib_v1")
    f2 = load_function_from_historical_file(root / "fibv2.py", "fib_pair")
    f3 = load_function_from_historical_file(root / "fibv3.py", "fib_fast")

    expected = {0: 0, 1: 1, 2: 1, 10: 55, 20: 6765}
    for n, answer in expected.items():
        if f1(n) != answer:
            raise RuntimeError(f"V1 correctness failure at F_{n}")
        if f2(n)[0] != answer:
            raise RuntimeError(f"V2 correctness failure at F_{n}")
        if f3(n) != answer:
            raise RuntimeError(f"V3 correctness failure at F_{n}")

    v4 = next(v for v in versions if v.key == "v4")
    probe = v4.measure_once(1000)
    if not math.isfinite(probe) or probe < 0:
        raise RuntimeError("V4 benchmark mode returned an invalid time")


def print_result(r: Result) -> None:
    s = r.sample
    print(
        f"  {r.version.label:<31} "
        f"F_{s.n:<13,d} "
        f"median {s.median:>9.6f} s  "
        f"{r.pct:>6.2f}%  "
        f"range {s.low:.6f}..{s.high:.6f}  "
        f"{r.status:<8} "
        f"runs {r.timed_runs:<3d} "
        f"wall {r.bench_wall:.2f}s"
    )


def run_fast(versions: list[Version], target: float) -> dict[str, Result]:
    print("\nFAST MODE — target zone 85-95%, center 90%")
    results: dict[str, Result] = {}
    for v in versions:
        print(f"Testing {v.label}...")
        r = fast_search(v, target)
        results[v.key] = r
        print_result(r)
    return results


def run_accurate(
    versions: list[Version],
    target: float,
    fast_results: Optional[dict[str, Result]] = None,
) -> dict[str, Result]:
    print("\nACCURATE MODE — certified median must be 99-100%")
    results: dict[str, Result] = {}
    for v in versions:
        print(f"Testing {v.label}...")
        seed = None
        if fast_results and v.key in fast_results:
            seed = fast_results[v.key].sample.n
        r = accurate_search(v, target, seed)
        results[v.key] = r
        print_result(r)
    return results


def parse_mode_and_target(argv: list[str]) -> tuple[str, float]:
    if len(argv) >= 2:
        raw = argv[1].lower()
        mode = {"1": "fast", "2": "accurate", "3": "both"}.get(raw, raw)
        if mode not in {"fast", "accurate", "both"}:
            raise ValueError("mode must be fast, accurate, or both")
        target = float(argv[2]) if len(argv) >= 3 else 1.0
        return mode, target

    print("\nFIBONACCI HISTORICAL BENCHMARK")
    print(f"Build: {RUNNER_BUILD}")
    print("1. Fast     - aims around 90%")
    print("2. Accurate - median must land 99-100%")
    print("3. Both")

    raw = input("\nChoose mode [1]: ").strip() or "1"
    mode = {"1": "fast", "2": "accurate", "3": "both"}.get(raw.lower(), raw.lower())
    if mode not in {"fast", "accurate", "both"}:
        raise ValueError("invalid mode")

    raw_target = input("Target seconds [1.0]: ").strip()
    target = float(raw_target) if raw_target else 1.0
    return mode, target


def main(argv: list[str]) -> int:
    try:
        mode, target = parse_mode_and_target(argv)
        if not math.isfinite(target) or target <= 0:
            raise ValueError("target must be greater than zero")

        # Use the runner's own folder, not whatever random folder PowerShell was
        # in when it was launched.
        root = Path(__file__).resolve().parent
        versions = load_versions(root)
        print("Preflight   : ", end="", flush=True)
        preflight(root, versions)
        print("OK")

    except Exception as exc:
        print(f"\nSETUP ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\nTarget      : {target:.6f} s")
    print("V1-V3 clock : time.perf_counter_ns() around function call only")
    print("V4 clock    : std::chrono::steady_clock inside fibv4.exe")
    print("Controller  : Python chooses n; controller overhead is NOT score time")

    total_start = time.perf_counter()
    fast_results: Optional[dict[str, Result]] = None

    try:
        if mode in {"fast", "both"}:
            fast_results = run_fast(versions, target)
        if mode in {"accurate", "both"}:
            run_accurate(versions, target, fast_results)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"\nBENCHMARK ERROR: {exc}", file=sys.stderr)
        return 1

    total_wall = time.perf_counter() - total_start
    print("\n" + "=" * 86)
    print(f"TOTAL BENCHMARK WALL TIME: {total_wall:.3f} s")
    print("=" * 86)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
