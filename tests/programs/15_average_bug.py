def average(marks):
    total = 0
    for i in range(1, len(marks)):
        total += marks[i]
    return total / len(marks)


marks = [80, 90, 70]
result = average(marks)
print(result)  # expected 80.0
