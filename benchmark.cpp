#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <utility>
#include <vector>

#include <gmp.h>
#include <gmpxx.h>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#else
#include <time.h>
#endif

using u64 = std::uint64_t;
using FibFn = mpz_class (*)(u64);

static volatile unsigned long g_sink = 0;
static void consume(const mpz_class& x) {
    g_sink ^= mpz_get_ui(x.get_mpz_t());
}

// ============================================================
// Fibonacci implementations
// ============================================================

mpz_class fib_v1(u64 n) {
    mpz_class a = 0, b = 1;
    for (u64 i = 0; i < n; ++i) {
        mpz_class next = a + b;
        a = std::move(b);
        b = std::move(next);
    }
    return a;
}

std::pair<mpz_class, mpz_class> fib_pair_v2(u64 n) {
    if (n == 0) return {0, 1};

    auto p = fib_pair_v2(n >> 1);
    const mpz_class& a = p.first;
    const mpz_class& b = p.second;

    mpz_class c = a * ((b << 1) - a);
    mpz_class d = a * a + b * b;

    if ((n & 1ULL) == 0) return {std::move(c), std::move(d)};
    return {d, c + d};
}

mpz_class fib_v2(u64 n) {
    return fib_pair_v2(n).first;
}

mpz_class fib_v3(u64 n) {
    if (n == 0) return 0;

    mpz_class a = 0, b = 1;
    int highest = 63;
    while (highest > 0 && ((n >> highest) & 1ULL) == 0) --highest;

    for (int bit = highest; bit >= 0; --bit) {
        mpz_class c = a * ((b << 1) - a);
        mpz_class d = a * a + b * b;

        if (((n >> bit) & 1ULL) == 0) {
            a = std::move(c);
            b = std::move(d);
        } else {
            mpz_class e = c + d;
            a = std::move(d);
            b = std::move(e);
        }
    }
    return a;
}

// Kept separate so V4 can be replaced later without touching the runner.
std::pair<mpz_class, mpz_class> fib_pair_v4(u64 n) {
    if (n == 0) return {0, 1};

    auto p = fib_pair_v4(n >> 1);
    mpz_class a = std::move(p.first);
    mpz_class b = std::move(p.second);

    mpz_class c = a * ((b << 1) - a);
    mpz_class d = a * a + b * b;

    if ((n & 1ULL) == 0) return {std::move(c), std::move(d)};
    return {d, c + d};
}

mpz_class fib_v4(u64 n) {
    return fib_pair_v4(n).first;
}

struct Impl {
    const char* name;
    FibFn fn;
    // Approximate local exponent t ~ n^p, used only as a conservative controller.
    // We do NOT fit p from noisy near-boundary timings.
    double p_hint;
};

static const Impl IMPLS[] = {
    {"V1 iterative",            fib_v1, 1.80},
    {"V2 recursive doubling",  fib_v2, 1.30},
    {"V3 iterative doubling",  fib_v3, 1.30},
    {"V4 GMP doubling",        fib_v4, 1.30},
};

// ============================================================
// Timing
// ============================================================

// Current-thread CPU time is the search metric. It excludes time where Windows
// deschedules the benchmark, which was the biggest source of the old 90%-110%
// swings. Wall time is still measured and printed beside it.
double cpu_now() {
#ifdef _WIN32
    FILETIME creation{}, exit{}, kernel{}, user{};
    if (!GetThreadTimes(GetCurrentThread(), &creation, &exit, &kernel, &user)) {
        return 0.0;
    }

    ULARGE_INTEGER k{}, u{};
    k.LowPart = kernel.dwLowDateTime;
    k.HighPart = kernel.dwHighDateTime;
    u.LowPart = user.dwLowDateTime;
    u.HighPart = user.dwHighDateTime;

    return static_cast<double>(k.QuadPart + u.QuadPart) * 1e-7;
#else
    timespec ts{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts) != 0) return 0.0;
    return static_cast<double>(ts.tv_sec) + static_cast<double>(ts.tv_nsec) * 1e-9;
#endif
}

struct OneSample {
    double cpu = 0.0;
    double wall = 0.0;
};

OneSample time_once(FibFn fn, u64 n) {
    auto w0 = std::chrono::steady_clock::now();
    double c0 = cpu_now();

    mpz_class result = fn(n);

    double c1 = cpu_now();
    auto w1 = std::chrono::steady_clock::now();
    consume(result);

    return {
        c1 - c0,
        std::chrono::duration<double>(w1 - w0).count()
    };
}

double median(std::vector<double> v) {
    std::sort(v.begin(), v.end());
    const std::size_t m = v.size() / 2;
    if (v.size() & 1U) return v[m];
    return 0.5 * (v[m - 1] + v[m]);
}

struct Measurement {
    double cpu = 0.0;
    double wall = 0.0;
    double min_cpu = 0.0;
    double max_cpu = 0.0;
    int samples = 0;
};

Measurement measure(FibFn fn, u64 n, int samples) {
    std::vector<double> cpus;
    std::vector<double> walls;
    cpus.reserve(samples);
    walls.reserve(samples);

    for (int i = 0; i < samples; ++i) {
        OneSample s = time_once(fn, n);
        cpus.push_back(s.cpu);
        walls.push_back(s.wall);
    }

    Measurement m;
    m.cpu = median(cpus);
    m.wall = median(walls);
    m.min_cpu = *std::min_element(cpus.begin(), cpus.end());
    m.max_cpu = *std::max_element(cpus.begin(), cpus.end());
    m.samples = samples;
    return m;
}

// ============================================================
// Controller helpers
// ============================================================

u64 scale_n(u64 n, long double factor) {
    if (n == 0) n = 1;

    long double x = static_cast<long double>(n) * factor;
    if (x < 1.0L) return 1;
    if (x >= static_cast<long double>(std::numeric_limits<u64>::max())) {
        return std::numeric_limits<u64>::max();
    }

    u64 out = static_cast<u64>(x);
    if (out == n) {
        if (factor > 1.0L && n < std::numeric_limits<u64>::max()) ++out;
        else if (factor < 1.0L && n > 1) --out;
    }
    return out;
}

void warmup(FibFn fn) {
    consume(fn(4096));
    consume(fn(4352));
}

// Cheaply get to roughly the right order of magnitude.
u64 coarse_seed(FibFn fn, double goal, double p_hint) {
    u64 n = 1024;
    double t = 0.0;

    for (int i = 0; i < 64; ++i) {
        t = time_once(fn, n).cpu;
        if (t >= goal * 0.20) break;

        if (n > std::numeric_limits<u64>::max() / 2) break;
        n *= 2;
    }

    if (t > 0.0) {
        long double factor = std::pow(
            static_cast<long double>(goal / t),
            1.0L / static_cast<long double>(p_hint)
        );
        factor = std::clamp(factor, 0.75L, 3.00L);
        n = scale_n(n, factor);
    }

    return n;
}

struct SearchResult {
    u64 n = 0;
    Measurement m;
    bool in_band = false;
};

// ============================================================
// FAST: aim around 90% of target
// ============================================================

SearchResult run_fast_one(const Impl& impl, double target) {
    const double goal = 0.90 * target;
    const double low = 0.86 * target;
    const double high = 0.94 * target;

    warmup(impl.fn);
    u64 n = coarse_seed(impl.fn, goal, impl.p_hint);

    // Cheap one-sample steering.
    for (int round = 0; round < 5; ++round) {
        double t = time_once(impl.fn, n).cpu;
        if (t >= low && t <= high) break;

        long double factor = std::pow(
            static_cast<long double>(goal / std::max(t, 1e-12)),
            1.0L / static_cast<long double>(impl.p_hint)
        );
        factor = std::clamp(factor, 0.78L, 1.28L);
        n = scale_n(n, factor);
    }

    Measurement m = measure(impl.fn, n, 3);

    // At most two corrections. Fast should stay fast.
    for (int round = 0; round < 4 && (m.cpu < low || m.cpu > high); ++round) {
        long double factor = std::pow(
            static_cast<long double>(goal / std::max(m.cpu, 1e-12)),
            1.0L / static_cast<long double>(impl.p_hint)
        );
        factor = std::clamp(factor, 0.84L, 1.16L);
        if (m.cpu > target) factor = std::min<long double>(factor, 0.92L);
        else if (m.cpu > high) factor = std::min<long double>(factor, 0.97L);
        else if (m.cpu < low) factor = std::max<long double>(factor, 1.03L);
        n = scale_n(n, factor);
        m = measure(impl.fn, n, 3);
    }

    return {n, m, m.cpu >= low && m.cpu <= high};
}

// ============================================================
// ACCURATE: certify a 99%-100% median
// ============================================================

SearchResult run_accurate_one(const Impl& impl, double target) {
    const double goal = 0.995 * target;
    const double low = 0.990 * target;
    const double high = 1.000 * target;

    warmup(impl.fn);
    u64 n = coarse_seed(impl.fn, goal, impl.p_hint);

    u64 best_n = 0;
    Measurement best_m{};

    auto remember_pass = [&](u64 candidate_n, const Measurement& m) {
        if (m.cpu <= target &&
            (best_n == 0 || m.cpu > best_m.cpu)) {
            best_n = candidate_n;
            best_m = m;
        }
    };

    // Stage A: median-of-3 feedback. This gets very close without spending
    // dozens of 1-second samples on binary-search points we do not care about.
    for (int round = 0; round < 9; ++round) {
        Measurement m = measure(impl.fn, n, 3);
        remember_pass(n, m);

        if (m.cpu >= low && m.cpu <= high) {
            Measurement verify = measure(impl.fn, n, 7);
            remember_pass(n, verify);
            if (verify.cpu >= low && verify.cpu <= high) {
                return {n, verify, true};
            }
            m = verify;
        }

        long double factor = std::pow(
            static_cast<long double>(goal / std::max(m.cpu, 1e-12)),
            1.0L / static_cast<long double>(impl.p_hint)
        );

        // Damped control. Close to the target, never jump by more than 3% in n.
        const double error = std::abs(m.cpu - goal) / target;
        if (error < 0.06) factor = std::clamp(factor, 0.970L, 1.030L);
        else              factor = std::clamp(factor, 0.850L, 1.150L);

        n = scale_n(n, factor);
    }

    // Stage B: high-confidence feedback with median-of-7.
    for (int round = 0; round < 6; ++round) {
        Measurement m = measure(impl.fn, n, 7);
        remember_pass(n, m);

        if (m.cpu >= low && m.cpu <= high) {
            return {n, m, true};
        }

        long double factor = std::pow(
            static_cast<long double>(goal / std::max(m.cpu, 1e-12)),
            1.0L / static_cast<long double>(impl.p_hint)
        );
        factor = std::clamp(factor, 0.975L, 1.025L);
        n = scale_n(n, factor);
    }

    // Stage C: final median-of-9 certification. If drift moved the candidate,
    // feed it back one last time rather than accepting an OVER result.
    for (int round = 0; round < 4; ++round) {
        Measurement m = measure(impl.fn, n, 9);
        remember_pass(n, m);

        if (m.cpu >= low && m.cpu <= high) {
            return {n, m, true};
        }

        long double factor = std::pow(
            static_cast<long double>(goal / std::max(m.cpu, 1e-12)),
            1.0L / static_cast<long double>(impl.p_hint)
        );
        factor = std::clamp(factor, 0.980L, 1.020L);
        n = scale_n(n, factor);
    }

    // Never lie. Re-check the closest under-target result; if it drifted OVER,
    // back off until a fresh 9-sample median is <= target.
    if (best_n != 0) {
        n = best_n;
        Measurement check = measure(impl.fn, n, 9);
        if (check.cpu >= low && check.cpu <= target) {
            return {n, check, true};
        }

        // If the best pass drifted slightly low, actively walk it back toward 99.5%.
        // This is intentionally slow/strong: Accurate mode is allowed to spend time.
        if (check.cpu < low) {
            for (int round = 0; round < 6; ++round) {
                long double factor = std::pow(
                    static_cast<long double>(goal / std::max(check.cpu, 1e-12)),
                    1.0L / static_cast<long double>(impl.p_hint)
                );
                factor = std::clamp(factor, 1.002L, 1.020L);
                u64 next = scale_n(n, factor);
                Measurement trial = measure(impl.fn, next, 9);

                if (trial.cpu >= low && trial.cpu <= target) {
                    return {next, trial, true};
                }

                if (trial.cpu > target) {
                    // Split the index interval instead of accepting OVER.
                    next = n + (next - n) / 2;
                    trial = measure(impl.fn, next, 9);
                    if (trial.cpu >= low && trial.cpu <= target) {
                        return {next, trial, true};
                    }
                    if (trial.cpu > target) {
                        // Keep n as the confirmed lower candidate.
                        check = measure(impl.fn, n, 9);
                        continue;
                    }
                }

                n = next;
                check = trial;
            }
        }

        if (check.cpu <= target && check.cpu >= low) {
            return {n, check, true};
        }
    }

    for (int round = 0; round < 8; ++round) {
        n = scale_n(n, 0.99L);
        Measurement m = measure(impl.fn, n, 9);
        if (m.cpu <= target) {
            return {n, m, m.cpu >= low};
        }
    }

    return {best_n, best_m, false};
}

// ============================================================
// Output / CLI
// ============================================================

void print_result(const Impl& impl, const SearchResult& r, double target) {
    double pct = (r.m.cpu / target) * 100.0;

    std::cout
        << std::left << std::setw(24) << impl.name
        << "F_" << std::setw(13) << r.n
        << " CPU " << std::fixed << std::setprecision(6) << r.m.cpu << " s"
        << "  " << std::setw(7) << std::setprecision(2) << pct << "%"
        << " wall " << std::setprecision(6) << r.m.wall << " s"
        << "  range " << r.m.min_cpu << ".." << r.m.max_cpu
        << "  " << (r.in_band ? "OK" : "UNSTABLE")
        << '\n';
}

void run_fast(double target) {
    std::cout << "\nFAST  (goal: about 90% of target)\n";
    for (const auto& impl : IMPLS) {
        print_result(impl, run_fast_one(impl, target), target);
    }
}

void run_accurate(double target) {
    std::cout << "\nACCURATE  (certified median goal: 99%-100% of target)\n";
    for (const auto& impl : IMPLS) {
        print_result(impl, run_accurate_one(impl, target), target);
    }
}

int main(int argc, char** argv) {
    std::string mode;
    double target = 1.0;

    if (argc >= 2) mode = argv[1];
    if (argc >= 3) {
        try { target = std::stod(argv[2]); }
        catch (...) { std::cerr << "Invalid target.\n"; return 1; }
    }

    if (mode != "fast" && mode != "accurate" && mode != "both") {
        std::cout
            << "FIBONACCI BENCHMARK RUNNER\n\n"
            << "Search metric: current-thread CPU time\n"
            << "Wall time is reported beside it.\n\n"
            << "1. Fast      (~90% target)\n"
            << "2. Accurate  (99%-100% target)\n"
            << "3. Both\n\n"
            << "Choice [1]: ";

        std::string choice;
        std::getline(std::cin, choice);
        if (choice.empty() || choice == "1") mode = "fast";
        else if (choice == "2") mode = "accurate";
        else if (choice == "3") mode = "both";
        else { std::cerr << "Invalid mode.\n"; return 1; }

        std::cout << "Target seconds [1.0]: ";
        std::string s;
        std::getline(std::cin, s);
        if (!s.empty()) {
            try { target = std::stod(s); }
            catch (...) { std::cerr << "Invalid target.\n"; return 1; }
        }
    }

    if (target <= 0.0) {
        std::cerr << "Target must be > 0.\n";
        return 1;
    }

    std::cout
        << "\nTarget: " << target << " s\n"
        << "Search metric: thread CPU time (scheduler pauses excluded)\n";

    if (mode == "fast" || mode == "both") run_fast(target);
    if (mode == "accurate" || mode == "both") run_accurate(target);

    if (g_sink == std::numeric_limits<unsigned long>::max()) {
        std::cerr << "sink=" << g_sink << '\n';
    }

    return 0;
}
