loop = int(input("what num of fib would you like: "))
n = 0
num = 0

n1 = 0
n2 = 1

while n < loop:
    temp = n1
    n1 = n2
    n2 = temp + n2
    n += 1

print(n1)