from fibv1 import fib_v1
from fibv2 import fib_pair
from fibv3 import fib_fast
import time

n = int(input("benchmark n: "))

runs = 100

v1_total = 0
v2_total = 0
v3_total = 0

for i in range(runs):
    start = time.perf_counter()
    fib_v1(n)
    v1_total += time.perf_counter() - start

for i in range(runs):
    start = time.perf_counter()
    fib_pair(n)
    v2_total += time.perf_counter() - start

for i in range(runs):
    start = time.perf_counter()
    fib_fast(n)
    v3_total += time.perf_counter() - start

print("V1 average:", v1_total / runs)
print("V2 average:", v2_total / runs)
print("V3 average:", v3_total / runs)