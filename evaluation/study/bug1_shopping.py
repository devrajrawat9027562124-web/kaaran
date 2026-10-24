# A shop gives 10% off every item. The bill should be 270.0
prices = [100, 200]
discount = 0.1
total = 0
for p in prices:
    discount = discount + 0.1
    total += p * (1 - discount)
print(total)
