def fib_v1(loop):
    n = 0
    n1 = 0
    n2 = 1

    while n < loop:
        temp = n1
        n1 = n2
        n2 = temp + n2
        n += 1

    return n1

loop = int(input("what num of fib would you like: "))
print(fib_v1(loop))