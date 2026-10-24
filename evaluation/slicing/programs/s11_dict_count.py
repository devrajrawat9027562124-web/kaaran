words = ["a", "b", "a"]
counts = {}
seen = 0
for w in words:
    counts[w] = counts.get(w, 0) + 1
    seen += 1
print(counts)
