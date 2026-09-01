from fibv1 import fib_v1
from fibv2 import fib_pair
from fibv3 import fib_fast

import math
import statistics
import subprocess
import time


CPP_EXE = ".\\fibv4.exe"

# ----------------------------
# Shared search settings
# ----------------------------

GROWTH_FACTOR = 8

# Fast mode:
# Mostly one-shot timings, then a small final verification.
FAST_SEARCH_TRIALS = 1
FAST_FINAL_TRIALS = 3
FAST_REFINE_STEPS = 5
FAST_TARGET_BAND = 0.97
FAST_MAX_CORRECTIONS = 2

# Accurate mode:
# Uses cheap timings to get near the answer, then spends its time only
# around the cutoff. The final answer is a verified median <= target.
ACCURATE_SEARCH_TRIALS = 1
ACCURATE_REFINE_TRIALS = 3
ACCURATE_FINAL_TRIALS = 5
ACCURATE_CHEAP_REFINE_STEPS = 6
ACCURATE_REFINE_STEPS = 12
ACCURATE_TARGET_BAND = 0.995   # try to get within 0.5% from below


def python_time(function, n, trials=1):
    """Return the median runtime of one Python Fibonacci calculation."""
    times = []

    for _ in range(trials):
        start = time.perf_counter()
        function(n)
        times.append(time.perf_counter() - start)

    return statistics.median(times)


def cpp_time(n, trials=1):
    """
    Ask fibv4.exe to benchmark fib_pair(n) internally.

    Process startup is NOT part of the reported Fibonacci runtime because
    fibv4.exe starts/stops its own timer around the Fibonacci calculation.
    """
    result = subprocess.run(
        [CPP_EXE, "--bench", str(n), str(trials)],
        capture_output=True,
        text=True,
        check=True,
    )

    output = result.stdout.strip()

    if not output:
        raise RuntimeError("fibv4.exe returned no benchmark timing")

    return float(output)


def estimate_power(low_n, low_time, high_n, high_time):
    """
    Estimate runtime scaling with:

        time ~= n ** p

    This is only used to make smarter guesses during the search.
    """
    if (
        low_n <= 0
        or high_n <= low_n
        or low_time <= 0
        or high_time <= low_time
    ):
        return 1.0

    try:
        p = math.log(high_time / low_time) / math.log(high_n / low_n)
    except (ValueError, ZeroDivisionError):
        return 1.0

    # Prevent noisy timings from producing absurd guesses.
    return max(0.35, min(4.0, p))


def smart_guess(low_n, low_time, high_n, high_time, target):
    """Predict an n near the requested runtime while staying inside the bracket."""
    if high_n - low_n <= 1:
        return low_n

    if low_n <= 0 or low_time <= 0:
        return (low_n + high_n) // 2

    p = estimate_power(low_n, low_time, high_n, high_time)

    try:
        guess = int(low_n * (target / low_time) ** (1.0 / p))
    except (ValueError, ZeroDivisionError, OverflowError):
        guess = (low_n + high_n) // 2

    # Keep the guess away from the exact edges so every step makes progress.
    width = high_n - low_n
    margin = max(1, int(width * 0.05))

    minimum = low_n + margin
    maximum = high_n - margin

    if minimum > maximum:
        return (low_n + high_n) // 2

    return max(minimum, min(maximum, guess))


def find_rough_bracket(timer, target):
    """
    Quickly find:
        low_n  -> measured <= target
        high_n -> measured > target

    Uses only one trial per point.
    """
    measurements = 0

    low_n = 0
    low_time = 0.0
    high_n = 64

    while True:
        high_time = timer(high_n, 1)
        measurements += 1

        if high_time > target:
            return low_n, low_time, high_n, high_time, measurements

        low_n = high_n
        low_time = high_time
        high_n *= GROWTH_FACTOR


def find_target_fast(timer, target):
    """
    FAST MODE

    Goal:
      Get close to the target quickly.

    Strategy:
      - x8 bracket search
      - a few smart one-trial guesses
      - median-of-3 final verification
      - at most a couple corrections

    This is intentionally approximate.
    """
    (
        low_n,
        low_time,
        high_n,
        high_time,
        measurements,
    ) = find_rough_bracket(timer, target)

    # Cheap predictive refinement.
    for _ in range(FAST_REFINE_STEPS):
        if high_n - low_n <= 1:
            break

        if low_time >= target * FAST_TARGET_BAND:
            break

        guess = smart_guess(low_n, low_time, high_n, high_time, target)

        if guess <= low_n or guess >= high_n:
            break

        guess_time = timer(guess, FAST_SEARCH_TRIALS)
        measurements += FAST_SEARCH_TRIALS

        if guess_time <= target:
            low_n = guess
            low_time = guess_time
        else:
            high_n = guess
            high_time = guess_time

    # Stable-ish final check.
    best_n = low_n
    final_time = timer(best_n, FAST_FINAL_TRIALS)
    measurements += FAST_FINAL_TRIALS

    # If final median crossed the target, make only a couple calculated moves down.
    corrections = 0

    while (
        final_time > target
        and best_n > 0
        and corrections < FAST_MAX_CORRECTIONS
    ):
        p = estimate_power(
            max(1, best_n),
            max(final_time, 1e-12),
            high_n,
            max(high_time, final_time * 1.001),
        )

        scale = (target / final_time) ** (1.0 / p)
        corrected_n = int(best_n * scale * 0.99)
        corrected_n = max(0, min(best_n - 1, corrected_n))

        best_n = corrected_n
        final_time = timer(best_n, FAST_FINAL_TRIALS)
        measurements += FAST_FINAL_TRIALS
        corrections += 1

    # One cheap upward attempt if we landed noticeably low.
    if (
        best_n > 0
        and final_time < target * FAST_TARGET_BAND
        and high_n - best_n > 1
    ):
        p = estimate_power(
            best_n,
            max(final_time, 1e-12),
            high_n,
            max(high_time, target * 1.001),
        )

        polished_n = int(
            best_n * (target / final_time) ** (1.0 / p) * 0.995
        )
        polished_n = max(best_n + 1, min(high_n - 1, polished_n))

        quick_time = timer(polished_n, 1)
        measurements += 1

        if quick_time <= target:
            polished_time = timer(polished_n, FAST_FINAL_TRIALS)
            measurements += FAST_FINAL_TRIALS

            if polished_time <= target and polished_time > final_time:
                best_n = polished_n
                final_time = polished_time

    return best_n, final_time, measurements


def find_target_accurate(timer, target):
    """
    ACCURATE MODE

    Goal:
      Find a verified result whose median runtime is as close as practical to
      the target WITHOUT exceeding it.

    Strategy:
      1. Cheap x8 bracket.
      2. Cheap predictive refinement to get near the cutoff.
      3. Re-measure the bracket with median-of-3 timings.
      4. Refine around the cutoff using median-of-3 timings.
      5. Final median-of-5 verification.

    This mode can be MUCH slower, especially with a 1+ second target.
    """
    (
        low_n,
        low_time,
        high_n,
        high_time,
        measurements,
    ) = find_rough_bracket(timer, target)

    # First get near the cutoff cheaply.
    for _ in range(ACCURATE_CHEAP_REFINE_STEPS):
        if high_n - low_n <= 1:
            break

        guess = smart_guess(low_n, low_time, high_n, high_time, target)

        if guess <= low_n or guess >= high_n:
            break

        guess_time = timer(guess, ACCURATE_SEARCH_TRIALS)
        measurements += ACCURATE_SEARCH_TRIALS

        if guess_time <= target:
            low_n = guess
            low_time = guess_time
        else:
            high_n = guess
            high_time = guess_time

    # Rebuild a stable PASS/FAIL bracket using medians.
    if low_n > 0:
        low_time = timer(low_n, ACCURATE_REFINE_TRIALS)
        measurements += ACCURATE_REFINE_TRIALS

    high_time = timer(high_n, ACCURATE_REFINE_TRIALS)
    measurements += ACCURATE_REFINE_TRIALS

    # Timing noise may invalidate the cheap bracket.
    # Move the lower point down until it is a verified pass.
    while low_n > 0 and low_time > target:
        p = estimate_power(
            max(1, low_n),
            max(low_time, 1e-12),
            high_n,
            max(high_time, low_time * 1.001),
        )

        scale = (target / low_time) ** (1.0 / p)
        new_low = int(low_n * scale * 0.98)
        new_low = max(0, min(low_n - 1, new_low))

        low_n = new_low

        if low_n == 0:
            low_time = 0.0
            break

        low_time = timer(low_n, ACCURATE_REFINE_TRIALS)
        measurements += ACCURATE_REFINE_TRIALS

    # And move the upper point up until it is a verified fail.
    while high_time <= target:
        low_n = high_n
        low_time = high_time
        high_n *= 2

        high_time = timer(high_n, ACCURATE_REFINE_TRIALS)
        measurements += ACCURATE_REFINE_TRIALS

    # Stable target-seeking refinement.
    for _ in range(ACCURATE_REFINE_STEPS):
        if high_n - low_n <= 1:
            break

        if low_n > 0 and low_time >= target * ACCURATE_TARGET_BAND:
            break

        guess = smart_guess(low_n, low_time, high_n, high_time, target)

        if guess <= low_n or guess >= high_n:
            guess = (low_n + high_n) // 2

        if guess <= low_n or guess >= high_n:
            break

        guess_time = timer(guess, ACCURATE_REFINE_TRIALS)
        measurements += ACCURATE_REFINE_TRIALS

        if guess_time <= target:
            low_n = guess
            low_time = guess_time
        else:
            high_n = guess
            high_time = guess_time

    # Final median-of-5 verification.
    best_n = low_n

    if best_n == 0:
        final_time = 0.0
        return best_n, final_time, measurements

    final_time = timer(best_n, ACCURATE_FINAL_TRIALS)
    measurements += ACCURATE_FINAL_TRIALS

    # If the stronger final verification goes over, correct downward until pass.
    while final_time > target and best_n > 0:
        p = estimate_power(
            max(1, best_n),
            max(final_time, 1e-12),
            high_n,
            max(high_time, final_time * 1.001),
        )

        scale = (target / final_time) ** (1.0 / p)
        corrected_n = int(best_n * scale * 0.995)
        corrected_n = max(0, min(best_n - 1, corrected_n))

        best_n = corrected_n

        if best_n == 0:
            final_time = 0.0
            break

        final_time = timer(best_n, ACCURATE_FINAL_TRIALS)
        measurements += ACCURATE_FINAL_TRIALS

    # If final verification landed too low, make a few careful upward attempts.
    polish_steps = 0

    while (
        best_n > 0
        and final_time < target * ACCURATE_TARGET_BAND
        and best_n + 1 < high_n
        and polish_steps < 4
    ):
        p = estimate_power(
            best_n,
            max(final_time, 1e-12),
            high_n,
            max(high_time, target * 1.001),
        )

        candidate = int(
            best_n * (target / final_time) ** (1.0 / p) * 0.998
        )
        candidate = max(best_n + 1, min(high_n - 1, candidate))

        candidate_time = timer(candidate, ACCURATE_FINAL_TRIALS)
        measurements += ACCURATE_FINAL_TRIALS

        if candidate_time <= target:
            best_n = candidate
            final_time = candidate_time
        else:
            high_n = candidate
            high_time = candidate_time

        polish_steps += 1

    return best_n, final_time, measurements


def choose_mode():
    print()
    print("Benchmark mode:")
    print("  1. Fast     - quick estimate, less precise")
    print("  2. Accurate - slower, tries to hug the target")
    print()

    choice = input("Choose mode [1]: ").strip()

    if choice in ("", "1"):
        return "fast"

    if choice == "2":
        return "accurate"

    print("Invalid choice. Using Fast mode.")
    return "fast"


def main():
    target = float(
        input("target time per Fibonacci calculation (seconds): ")
    )

    if target <= 0:
        raise ValueError("target time must be greater than 0")

    mode = choose_mode()

    versions = [
        ("V1 Python", lambda n, trials: python_time(fib_v1, n, trials)),
        ("V2 Python", lambda n, trials: python_time(fib_pair, n, trials)),
        ("V3 Python", lambda n, trials: python_time(fib_fast, n, trials)),
        ("V4 C++/GMP", cpp_time),
    ]

    if mode == "fast":
        finder = find_target_fast
        mode_name = "FAST"
        explanation = (
            "Mostly 1-trial searching + median-of-3 final verification."
        )
    else:
        finder = find_target_accurate
        mode_name = "ACCURATE"
        explanation = (
            "Median-based cutoff refinement + median-of-5 final verification."
        )

    print()
    print(f"{mode_name} TARGET BENCHMARK")
    print(f"Target runtime: {target:.6f} s")
    print(explanation)
    print()

    results = []
    whole_start = time.perf_counter()

    for name, timer in versions:
        print(f"Testing {name}...")
        version_start = time.perf_counter()

        n, measured_time, measurements = finder(timer, target)

        wall_time = time.perf_counter() - version_start
        difference = target - measured_time

        results.append(
            (name, n, measured_time, difference, wall_time, measurements)
        )

        status = "PASS" if measured_time <= target else "OVER"

        print(
            f"  {status} | highest found = F_{n:,} | "
            f"time = {measured_time:.6f} s | "
            f"bench took {wall_time:.2f} s "
            f"({measurements} timed runs)"
        )

    whole_time = time.perf_counter() - whole_start

    print()
    print("RESULTS")
    print("-" * 92)
    print(
        f"{'Version':<16}"
        f"{'Highest F_n found':>24}"
        f"{'Measured time':>20}"
        f"{'Below target':>16}"
        f"{'Bench wall':>16}"
    )
    print("-" * 92)

    for name, n, measured_time, difference, wall_time, _ in results:
        below_text = (
            f"{difference:.6f} s"
            if difference >= 0
            else f"OVER {-difference:.6f}"
        )

        print(
            f"{name:<16}"
            f"{('F_' + format(n, ',')):>24}"
            f"{(format(measured_time, '.6f') + ' s'):>20}"
            f"{below_text:>16}"
            f"{(format(wall_time, '.2f') + ' s'):>16}"
        )

    print("-" * 92)
    print(f"Total benchmark wall time: {whole_time:.2f} s")

    if mode == "fast":
        print()
        print(
            "Fast mode is intentionally approximate. Use Accurate mode when "
            "you want the cutoff measured much closer to the target."
        )
    else:
        print()
        print(
            "Accurate mode uses repeated median timings, so it can take a while. "
            "Small timing wiggles are still normal because runtime is never perfectly deterministic."
        )


if __name__ == "__main__":
    main()