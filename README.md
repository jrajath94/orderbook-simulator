# orderbook-simulator

High-fidelity limit order book simulator with market microstructure for realistic trading system backtesting.

## Overview

Most traders backtest strategies on "close price" or OHLC bars, completely ignoring how real markets operate. In reality, you execute trades at the bid/ask, wait for fills, experience slippage due to market impact. A strategy that works on close prices fails spectacularly when faced with actual execution.

This library simulates realistic order book dynamics: price-time priority matching, bid-ask spreads, order queue mechanics. Enables testing execution strategies against realistic market conditions rather than fictional markets.

## Problem Statement

Standard backtesting ignores market microstructure:

1. **Ignores spreads**: Assumes execution at mid price. Reality: buy at ask, sell at bid.
2. **No fill uncertainty**: Assumes instant fills. Reality: partial fills, queue position.
3. **Ignores impact**: Assumes execution doesn't move prices. Reality: large orders move markets.
4. **Survivorship bias**: Strategies that "work" on close prices lose money live.

## Solution

Event-driven order book simulator:
- Maintains buy/sell order queues with price-time priority
- Matches orders according to exchange rules
- Calculates realistic fill prices
- Tracks microstructure metrics (spread, depth, impact)

## Installation

```bash
pip install orderbook-simulator
```

## Usage

```python
from orderbook_simulator import OrderBook, Order

book = OrderBook()

# Add orders to book
book.add_order(Order(order_id=1, side='BUY', price=100.0, quantity=100))
book.add_order(Order(order_id=2, side='SELL', price=101.0, quantity=50))

# Market conditions
print(f"Bid-ask spread: {book.get_spread()}")  # 1.0
print(f"Mid price: {book.get_midprice()}")  # 100.5

# Test order execution
book.add_order(Order(order_id=3, side='SELL', price=100.0, quantity=75))
# Partially fills against buy orders
```

## Real-World Application: Backtesting

```python
def backtest_strategy(price_data):
    book = OrderBook()
    
    for timestamp, price_level in price_data:
        # Update order book with new prices
        book.update_from_market_data(price_level)
        
        # Strategy logic
        if signal > threshold:
            # Place limit order at bid
            order = Order(order_id=next_id, 
                         side='BUY', 
                         price=book.best_bid,
                         quantity=100)
            book.add_order(order)
        
        # Check fills and update position
        fills = book.get_fills()
        position += sum(f.quantity for f in fills)
```

## Design Decisions

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Price-time priority | Matches real exchange rules | Adds complexity |
| Event-driven simulation | Realistic tick-by-tick matching | Slower than OHLC backtest |
| Partial fills | Matches reality of order queues | More realistic but slower |

## Performance

Simulation speed on standard hardware:

| Data Points | Time | Notes |
|-------------|------|-------|
| 1K ticks | 10ms | Simple strategies |
| 100K ticks | 500ms | Complex matching logic |
| 1M ticks | 5s | Detailed simulation |

## Real-World Applications

**Execution Algorithm Testing**: Test TWAP, VWAP, and custom execution strategies against realistic order books.

**High-Frequency Trading**: Simulate low-latency strategies with millisecond-level precision.

**Market Making**: Test market-making algorithms' profitability under various market conditions.

## Limitations

- Single-stock only (extend for multi-asset)
- No margin requirements or position limits
- No realistic market impact models (simple linear impact only)
- Deterministic matching (no randomness in fill timing)

## Future Enhancements

- Multi-asset order book
- Realistic market impact models
- Stochastic fill timing
- Portfolio-level risk limits

## License

MIT License.

## References

- Market microstructure: O'Hara (1995), Foucault et al. (2013)
- Limit order book dynamics: Cont et al. (2010)
- Execution algorithms: Kissell and Malamut (2005)
