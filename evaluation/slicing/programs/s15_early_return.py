def first_negative(values):
    for v in values:
        if v < 0:
            return v
    return None

data = [3, -2, -5]
flag = True
found = first_negative(data)
print(found)
