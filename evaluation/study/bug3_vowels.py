# Count the vowels in a sentence. It should print 8
sentence = "Kaaran explains code"
for ch in sentence:
    count = 0
    if ch in "aeiou":
        count += 1
print(count)
