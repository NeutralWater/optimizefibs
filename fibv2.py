def fib_pair(n):
    def f_even(a,b):
        return 2*b*a - a*a

    def f_odd(a,b):
        return a**2 + b**2

    if n == 0:
        return 0,1

    a,b = fib_pair(n // 2)

    c = f_even(a,b)
    d = f_odd(a,b)

    if n % 2 == 0:
        return c,d
    else:
        return d, c + d


if __name__ == "__main__":
    n = int(input("what num of fib would you like: "))
    r, nr = fib_pair(n)
    print(r)