def add_bonus(marks, extra):
    for i in range(len(marks)):
        marks[i] += extra

scores = [50, 60]
bonus = 5
other = 1
add_bonus(scores, bonus)
print(scores)
