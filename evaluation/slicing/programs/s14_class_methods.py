class Account:
    def __init__(self, balance):
        self.balance = balance

    def deposit(self, amount):
        self.balance += amount

acc = Account(100)
fee = 2
acc.deposit(50)
print(acc.balance)
