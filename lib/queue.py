class Queue:
    def __init__(self) -> None:
        self.queue = []
    def __len__(self):
        return len(self.queue)
    def dequeue(self):
        if not self.queue:
            raise IndexError("dequeue from empty queue")
        return self.queue.pop(0)
    def enqueue(self, element):
        self.queue.append(element)
    def is_empty(self):
        return len(self.queue) == 0

