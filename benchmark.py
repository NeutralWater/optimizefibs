# FIBONACCI HISTORICAL RUNNER
# BUILD: exact-target-v3.0 / 2026-09-01

from __future__ import annotations
import ast, hashlib, math, os, statistics, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BUILD = "exact-target-v3.0 / 2026-09-01"
ROOT = Path(__file__).resolve().parent
V1_FILE, V2_FILE, V3_FILE = ROOT/'fibv1.py', ROOT/'fibv2.py', ROOT/'fibv3.py'
V4_EXE = ROOT / ('fibv4.exe' if os.name == 'nt' else 'fibv4')
Timer = Callable[[int, int], tuple[float, list[float]]]

@dataclass
class Candidate:
    n: int
    median: float
    samples: list[float]
    def error(self, target: float) -> float:
        return abs(self.median-target)/target
    def percent(self, target: float) -> float:
        return self.median/target*100.0

def sha12(path): return hashlib.sha256(path.read_bytes()).hexdigest()[:12]

def load_function_only(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    keep = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Import,ast.ImportFrom))]
    mod = ast.Module(body=keep, type_ignores=[]); ast.fix_missing_locations(mod)
    ns={'__name__':'_fib_benchmark_loaded_'}
    exec(compile(mod,str(path),'exec'),ns,ns)
    f=ns.get(name)
    if not callable(f): raise RuntimeError(f'{name} not found in {path.name}')
    return f

def python_timer(func):
    def timer(n,trials):
        xs=[]
        for _ in range(max(1,trials)):
            s=time.perf_counter_ns(); r=func(n); e=time.perf_counter_ns()
            if r is None: raise RuntimeError('Fibonacci function returned None')
            xs.append((e-s)/1e9)
        return statistics.median(xs),xs
    return timer

def cpp_timer(n,trials):
    xs=[]
    for _ in range(max(1,trials)):
        cp=subprocess.run([str(V4_EXE),'--bench',str(n),'1'],cwd=ROOT,capture_output=True,text=True,check=True)
        out=cp.stdout.strip()
        if not out: raise RuntimeError('fibv4.exe produced no timing')
        xs.append(float(out.splitlines()[-1]))
    return statistics.median(xs),xs

def measure(timer,n,trials):
    med,xs=timer(max(0,int(n)),trials); return Candidate(max(0,int(n)),med,xs)

def better(a,b,target):
    if a is None or b.error(target)<a.error(target): return b
    if abs(b.error(target)-a.error(target))<1e-12 and b.n>a.n: return b
    return a

def warmup(timer):
    try: timer(1000,1)
    except Exception: pass

def rough_bracket(timer,target,start=1024):
    n=max(2,start); low=Candidate(0,0.0,[0.0]); visited=[low]; runs=0
    while True:
        c=measure(timer,n,1); runs+=1; visited.append(c)
        if c.median<target:
            low=c; n*=2; continue
        c=measure(timer,n,3); runs+=3; visited.append(c)
        if c.median>=target: return low,c,visited,runs
        low=c; n*=2

def interpolated_n(low,high,target):
    lo,hi=low.n,high.n
    if hi-lo<=2: return lo+(hi-lo)//2
    dt=high.median-low.median
    if dt<=1e-12: g=(lo+hi)//2
    else:
        f=(target-low.median)/dt; f=min(.85,max(.15,f)); g=lo+int((hi-lo)*f)
    return min(hi-1,max(lo+1,g))

def classify(err):
    p=err*100
    return 'EXCELLENT' if p<=.10 else 'GREAT' if p<=.25 else 'GOOD' if p<=.50 else 'CLOSE' if p<=1 else 'NOISY'

def search_fast(timer,user_target):
    desired=user_target*.90
    low,high,seen,runs=rough_bracket(timer,desired)
    best=None
    for c in seen: best=better(best,c,desired)
    for _ in range(7):
        if high.n-low.n<=2: break
        c=measure(timer,interpolated_n(low,high,desired),1); runs+=1; best=better(best,c,desired)
        if c.median<desired: low=c
        else: high=c
    best=measure(timer,best.n,3); runs+=3
    pct=best.median/user_target
    if pct<.85 or pct>.95:
        rn=max(1,int(best.n*desired/max(best.median,1e-12)))
        r=measure(timer,rn,3); runs+=3
        if abs(r.median-desired)<abs(best.median-desired): best=r
    return best,runs

def search_accurate(timer,target):
    """
    STUBBORN accurate mode.

    Keep moving n higher/lower until we are genuinely very close to the
    user's requested runtime. 98% is NOT a finish line.

    Stop conditions:
      1) certified median is within 0.10% of target, OR
      2) the integer n bracket collapses, OR
      3) we exhaust a large search budget.

    We always remember the closest median ever seen, whether it is
    slightly UNDER or slightly OVER the target.
    """
    low,high,seen,runs=rough_bracket(timer,target)
    best=None
    cand={}

    for c in seen:
        cand[c.n]=c
        best=better(best,c,target)

    # Search much more stubbornly than v3.
    # Trial count increases automatically as we approach the bullseye.
    for _ in range(40):
        if high.n-low.n<=1:
            break

        current_error=best.error(target)

        if current_error > .02:       # >2% away
            trials=3
        elif current_error > .005:    # 0.5%-2%
            trials=5
        else:                         # already close
            trials=7

        n=interpolated_n(low,high,target)

        # Avoid repeatedly testing the same point when interpolation rounds.
        if n in cand and high.n-low.n>2:
            n=(low.n+high.n)//2
            if n in cand:
                n=min(high.n-1,max(low.n+1,n+1))

        c=measure(timer,n,trials)
        runs+=trials
        cand[n]=c
        best=better(best,c,target)

        if c.median<target:
            low=c
        else:
            high=c

        # Proportional bullseye shot from the best measurement so far.
        # This is especially useful when we are sitting at 97-99%.
        if best.error(target) <= .03 and high.n-low.n>1:
            ratio=target/max(best.median,1e-12)
            bn=max(low.n+1,min(high.n-1,int(round(best.n*ratio))))

            if bn not in cand and low.n < bn < high.n:
                btrials=5 if best.error(target)>.005 else 7
                b=measure(timer,bn,btrials)
                runs+=btrials
                cand[bn]=b
                best=better(best,b,target)

                if b.median<target:
                    low=b
                else:
                    high=b

        # Once search measurements themselves are very close, certify now.
        if best.error(target) <= .001:   # <=0.10%
            cert=measure(timer,best.n,9)
            runs+=9
            cand[best.n]=cert
            best=better(best,cert,target)
            if cert.error(target) <= .001:
                return cert,runs

    # Search is over or bracket collapsed.
    # Certify several of the strongest candidates with heavier sampling.
    ranked=sorted(cand,key=lambda n:cand[n].error(target))
    final=None

    for n in ranked[:5]:
        c=measure(timer,n,9)
        runs+=9
        final=better(final,c,target)

        if c.error(target)<=.001:
            # One stronger confirmation before accepting the bullseye.
            confirm=measure(timer,n,11)
            runs+=11
            final=better(final,confirm,target)
            if confirm.error(target)<=.001:
                return confirm,runs

    # If certification knocked us away from target, keep correcting.
    # Do NOT quit at 98%. Up to 10 extra feedback rounds.
    for _ in range(10):
        if final.error(target)<=.001:
            break

        ratio=target/max(final.median,1e-12)
        n=max(1,int(round(final.n*ratio)))

        if n==final.n:
            n=max(1,n+(1 if final.median<target else -1))

        c=measure(timer,n,7)
        runs+=7
        final=better(final,c,target)

        if c.error(target)<=.001:
            confirm=measure(timer,c.n,11)
            runs+=11
            final=better(final,confirm,target)
            if confirm.error(target)<=.001:
                return confirm,runs

    # Final strongest measurement. This can still miss 0.10% if the machine's
    # timing noise is larger than the requested precision, but it will return
    # the closest result we actually measured rather than giving up at 98%.
    winner=measure(timer,final.n,13)
    runs+=13

    if winner.error(target) <= final.error(target):
        return winner,runs

    # Final's earlier median was closer; re-certify it once so the returned
    # result always corresponds to a fresh heavy sample set.
    retry=measure(timer,final.n,13)
    runs+=13
    return retry,runs

def fmt_range(xs): return '-' if not xs else f'{min(xs):.6f}..{max(xs):.6f}'

def print_result(name,c,target,runs,wall,fast=False):
    pct=c.percent(target); err=c.error(target)*100
    label=('OK' if 85<=pct<=95 else '~') if fast else classify(c.error(target))
    side='UNDER' if c.median<target else 'OVER' if c.median>target else 'EXACT'
    print(f'  {name:<29} F_{c.n:,}')
    print(f'      median {c.median:.6f} s | {pct:7.3f}% target | error {err:.3f}% | {side} | {label}')
    print(f'      range {fmt_range(c.samples)} | runs {runs} | wall {wall:.2f}s')

def preflight():
    for p in (V1_FILE,V2_FILE,V3_FILE):
        if not p.exists(): raise FileNotFoundError(f'Missing {p.name}')
    if not V4_EXE.exists(): raise FileNotFoundError(f'Missing {V4_EXE.name}. Compile fibv4.cpp first.')
    f1=load_function_only(V1_FILE,'fib_v1'); f2=load_function_only(V2_FILE,'fib_pair'); f3=load_function_only(V3_FILE,'fib_fast')
    if f1(20)!=6765 or f2(20)[0]!=6765 or f3(20)!=6765: raise RuntimeError('Python correctness preflight failed')
    cpp_timer(1000,1)
    return [('V1 Python iterative',python_timer(f1)),('V2 Python recursive doubling',python_timer(f2)),('V3 Python iterative doubling',python_timer(f3)),('V4 C++/GMP doubling',cpp_timer)]

def run_mode(versions,mode,target):
    if mode=='fast': print(f'\nFAST MODE — aiming for ~90% of user target ({target*.90:.6f} s)')
    else:
        print(f'\nACCURATE MODE — chasing exact requested target ({target:.6f} s)')
        print('Slightly UNDER and slightly OVER are equally valid; absolute error wins.')
    for name,timer in versions:
        print(f'\nTesting {name}...'); warmup(timer); w=time.perf_counter()
        c,runs=(search_fast(timer,target) if mode=='fast' else search_accurate(timer,target))
        print_result(name,c,target,runs,time.perf_counter()-w,fast=(mode=='fast'))

def main():
    print('FIBONACCI HISTORICAL BENCHMARK'); print(f'Runner build : {BUILD}\n')
    print('1. Fast     - aims around 90% of requested runtime')
    print('2. Accurate - chases requested runtime as closely as possible')
    print('3. Both\n')
    choice=input('Choose mode [1]: ').strip() or '1'
    try: target=float(input('Target seconds [1.0]: ').strip() or '1.0')
    except ValueError: print('Invalid target.'); return 1
    if target<=0: print('Target must be > 0.'); return 1
    try: versions=preflight()
    except Exception as e: print(f'\nPREFLIGHT ERROR: {e}'); return 1
    print(f'\nLoaded V1 : {V1_FILE.name} sha256 {sha12(V1_FILE)}')
    print(f'Loaded V2 : {V2_FILE.name} sha256 {sha12(V2_FILE)}')
    print(f'Loaded V3 : {V3_FILE.name} sha256 {sha12(V3_FILE)}')
    print(f'Loaded V4 : {V4_EXE.name}\nPreflight : OK')
    print(f'\nUser target : {target:.6f} s')
    print('V1-V3 clock: time.perf_counter_ns() around function call only')
    print('V4 clock   : std::chrono::steady_clock inside fibv4.exe')
    print('Controller : chooses n between timed runs; controller overhead is not score time')
    total=time.perf_counter()
    if choice=='1': run_mode(versions,'fast',target)
    elif choice=='2': run_mode(versions,'accurate',target)
    elif choice=='3': run_mode(versions,'fast',target); run_mode(versions,'accurate',target)
    else: print('Invalid mode.'); return 1
    print('\n'+'='*76); print(f'TOTAL BENCHMARK WALL TIME: {time.perf_counter()-total:.3f} s'); print('='*76)
    return 0

if __name__=='__main__': raise SystemExit(main())
