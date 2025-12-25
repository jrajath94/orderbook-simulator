from dataclasses import dataclass
from typing import List

@dataclass
class Order:
    order_id: int
    side: str  # 'BUY' or 'SELL'
    price: float
    quantity: int
    timestamp: float

class OrderBook:
    def __init__(self):
        self.bids: List[Order] = []
        self.asks: List[Order] = []
    
    def add_order(self, order: Order) -> None:
        """Add order to book."""
        if order.side == 'BUY':
            self.bids.append(order)
            self.bids.sort(key=lambda x: -x.price)
        else:
            self.asks.append(order)
            self.asks.sort(key=lambda x: x.price)
    
    def get_midprice(self) -> float:
        """Get midprice."""
        if self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2
        return 0.0
    
    def get_spread(self) -> float:
        """Get bid-ask spread."""
        if self.bids and self.asks:
            return self.asks[0].price - self.bids[0].price
        return 0.0
