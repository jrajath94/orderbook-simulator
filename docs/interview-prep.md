# Interview Prep: orderbook-simulator

## Elevator Pitch

High-fidelity limit order book simulator for realistic backtesting. Maintains price-time priority, matches orders, calculates microstructure metrics (spread, depth, impact). Foundation for testing execution algorithms in quant trading.

## Why It Matters

Market data isn't random. Order book dynamics (bid-ask spread, fill probability, slippage) are critical for real execution. Backtests that ignore order book = unrealistic.

## Key Components

1. **Order Queue**: Buy/sell orders sorted by price (primary), time (secondary)
2. **Matching Logic**: When orders arrive, match against opposite side
3. **Microstructure**: Spread, depth, impact calculations

## Interview Angle

Show you understand markets are *structured* systems with specific rules. Ask: "Have you tested your trading strategy against realistic microstructure?"

