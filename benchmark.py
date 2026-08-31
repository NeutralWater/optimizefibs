from fibv1 import fib_v1
from fibv2 import fib_pair
from fibv3 import fib_fast
import time

n = int(input("benchmark n: "))

start = time.perf_counter()
r1 = fib_v1(n)
print("V1:", time.perf_counter() - start)

start = time.perf_counter()
r2 = fib_pair(n)
print("V2:", time.perf_counter() - start)

start = time.perf_counter()
r3 = fib_fast(n)
print("V3:", time.perf_counter() - start)