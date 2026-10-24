class Counter:
    def __init__(self):
        self.value = 0

    def add(self, amount):
        self.value += amount


c = Counter()
c.add(2)
c.add(3)
print(c.value)
