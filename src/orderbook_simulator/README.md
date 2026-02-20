# orderbook_simulator Module

Event-driven order book with realistic matching.

## Components

- **orderbook.py**: Main OrderBook class
  - Maintains buy/sell FIFO queues
  - Matches incoming orders against queues
  - Tracks best bid/ask/spread

- **order.py**: Order data structure
  - Immutable order representation
  - Tracks original submission time
  - Used for fill generation

## Matching Logic

When a buy order arrives:
1. Check if price crosses any sell orders
2. Match against best sellers (lowest price, earliest submission)
3. Generate trades + execution reports
4. Post remainder to book (or cancel if post-only)

The key: FIFO within price level ensures fairness. Early submitters get filled first.
