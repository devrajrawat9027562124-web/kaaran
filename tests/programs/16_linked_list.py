class Node:
    def __init__(self, value):
        self.value = value
        self.next = None


head = Node(1)
head.next = Node(2)
head.next.next = Node(3)
total = 0
node = head
while node is not None:
    total += node.value
    node = node.next
print(total)
