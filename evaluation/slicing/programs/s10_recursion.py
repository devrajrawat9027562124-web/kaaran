def power(b, e):
    if e == 0:
        return 1
    return b * power(b, e - 1)

base = 2
unused = 99
result = power(base, 3)
print(result)
