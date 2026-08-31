def fib_fast(n):
    binary = bin(n)[2:]

    def f_even(a,b):
        return 2*b*a - a*a

    def f_odd(a,b):
        return a**2 + b**2

    a = 0
    b = 1

    for bit in binary:
        c = f_even(a,b)
        d = f_odd(a,b)

        if bit == '0':
            a,b = c,d
        else:
            a,b = d, c + d
    return a

if __name__ == "__main__":
    n = int(input("what num of fib would you like: "))
    print(fib_fast(n))