"""One spend ledger shared by all workers. Reserve worst-case cost before dispatch; settle with actual
usage after. Admission stops when spent + reserved + next reservation would exceed the cap."""
import threading


class BudgetExceeded(Exception):
    pass


class Ledger:
    def __init__(self, cap_usd, already_spent=0.0):
        self.cap = cap_usd
        self.spent = already_spent
        self.reserved = 0.0
        self.lock = threading.Lock()

    def reserve(self, amount):
        with self.lock:
            if self.spent + self.reserved + amount > self.cap:
                raise BudgetExceeded(f"spent {self.spent:.6f} + reserved {self.reserved:.6f} + next "
                                     f"{amount:.6f} > cap {self.cap:.6f}")
            self.reserved += amount
            return amount

    def settle(self, reservation, actual):
        """Release a reservation and book actual cost. Unknown actual (timeout) books the full reservation."""
        with self.lock:
            self.reserved -= reservation
            self.spent += reservation if actual is None else actual

    def snapshot(self):
        with self.lock:
            return {"cap": self.cap, "spent": round(self.spent, 8), "reserved": round(self.reserved, 8)}
