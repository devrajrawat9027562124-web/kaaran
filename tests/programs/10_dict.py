text = "the cat and the hat"
counts = {}
for w in text.split():
    counts[w] = counts.get(w, 0) + 1
print(counts["the"])
