# Keep a backup of the marks before adding grace marks.
# The backup should still be [35, 48, 60]
marks = [35, 48, 60]
backup = marks
for i in range(len(marks)):
    if marks[i] < 40:
        marks[i] = 40
print("now:", marks)
print("backup:", backup)
