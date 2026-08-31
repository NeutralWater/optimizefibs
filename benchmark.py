from fibv1 import fib_v1
from fibv2 import fib_pair
from fibv3 import fib_fast

import math
import statistics
import subprocess
import time


TRIALS = 3
CPP_EXE = ".\\fibv4.exe"


def python_time(function, n, trials=TRIALS):
    """Median time for one Fibonacci calculation."""
    times = []

    for _ in range(trials):
        start = time.perf_counter()
        function(n)
        times.append(time.perf_counter() - start)

    return statistics.median(times)


def cpp_time(n, trials=TRIALS):
    """Ask V4 to time fib_pair(n) internally, excluding process startup."""
    result = subprocess.run(
        [CPP_EXE, "--bench", str(n), str(trials)],
        capture_output=True,
        text=True,
        check=True,
    )

    return float(result.stdout.strip())


def find_max_n(timer, time_limit):
    """
    Find the largest Fibonacci index whose median computation time
    is at or below time_limit.

    First doubles n to find the failing range, then binary-searches it.
    """
    low = 0
    high = 1

    # Exponential search: 1, 2, 4, 8, 16, ...
    while timer(high) <= time_limit:
        low = high
        high *= 2

    # Binary search between last pass and first fail.
    while low + 1 < high:
        mid = (low + high) // 2

        if timer(mid) <= time_limit:
            low = mid
        else:
            high = mid

    # Re-measure the winner for the displayed time.
    final_time = timer(low)
    return low, final_time


def fib_digits(n):
    """Number of decimal digits in F_n without converting F_n to a string."""
    if n == 0:
        return 1
    if n == 1:
        return 1

    phi = (1 + math.sqrt(5)) / 2
    return math.floor(n * math.log10(phi) - math.log10(math.sqrt(5))) + 1


def main():
    time_limit = float(input("time limit per Fibonacci calculation (seconds): "))

    if time_limit <= 0:
        raise ValueError("time limit must be greater than 0")

    versions = [
        ("V1 Python", lambda n: python_time(fib_v1, n)),
        ("V2 Python", lambda n: python_time(fib_pair, n)),
        ("V3 Python", lambda n: python_time(fib_fast, n)),
        ("V4 C++/GMP", cpp_time),
    ]

    print()
    print(f"Finding the largest F_n computable in <= {time_limit:g} seconds")
    print(f"Timing uses the median of {TRIALS} trials per candidate.\n")

    results = []

    for name, timer in versions:
        print(f"Testing {name}...")
        n, measured_time = find_max_n(timer, time_limit)
        digits = fib_digits(n)
        results.append((name, n, digits, measured_time))
        print(f"  max n = {n:,} | digits = {digits:,} | time = {measured_time:.6f} s")

    print("\nRESULTS")
    print("-" * 78)
    print(f"{'Version':<16} {'Max n':>16} {'Digits in F_n':>18} {'Measured time':>18}")
    print("-" * 78)

    for name, n, digits, measured_time in results:
        print(f"{name:<16} {n:>16,} {digits:>18,} {measured_time:>17.6f} s")


if __name__ == "__main__":
    main()