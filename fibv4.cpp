#include <algorithm>
#include <chrono>
#include <iostream>
#include <string>
#include <utility>
#include <vector>
#include <gmpxx.h>

std::pair<mpz_class, mpz_class> fib_pair(unsigned long long n) {
    if (n == 0) {
        return {0, 1};
    }

    auto result = fib_pair(n / 2);

    mpz_class a = result.first;
    mpz_class b = result.second;

    mpz_class c = a * (2 * b - a);
    mpz_class d = a * a + b * b;

    if (n % 2 == 0) {
        return {c, d};
    }

    return {d, c + d};
}

// Keeps benchmark results observable so the compiler cannot throw the work away.
volatile unsigned long benchmark_sink = 0;

double benchmark(unsigned long long n, int trials) {
    std::vector<double> times;
    times.reserve(trials);

    for (int i = 0; i < trials; ++i) {
        auto start = std::chrono::steady_clock::now();
        auto result = fib_pair(n);
        auto end = std::chrono::steady_clock::now();

        benchmark_sink ^= mpz_get_ui(result.first.get_mpz_t());

        std::chrono::duration<double> elapsed = end - start;
        times.push_back(elapsed.count());
    }

    std::sort(times.begin(), times.end());
    return times[times.size() / 2];
}

int main(int argc, char* argv[]) {
    // Benchmark mode:
    //   .\fibv4.exe --bench 100000 3
    // Prints only the median time in seconds.
    if (argc >= 3 && std::string(argv[1]) == "--bench") {
        unsigned long long n = std::stoull(argv[2]);
        int trials = (argc >= 4) ? std::stoi(argv[3]) : 3;

        if (trials < 1) {
            trials = 1;
        }

        std::cout.precision(17);
        std::cout << benchmark(n, trials) << "\n";
        return 0;
    }

    // Normal interactive mode.
    unsigned long long n;
    std::cout << "what num of fib would you like: ";
    std::cin >> n;

    auto result = fib_pair(n);
    std::cout << result.first << "\n";

    return 0;
}
