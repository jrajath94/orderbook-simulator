"""High-fidelity limit order book simulator with matching engine.

Implements a price-time priority matching engine supporting limit orders,
market orders, and IOC (immediate-or-cancel) orders. Tracks full trade
history and provides real-time book state queries.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)

# Tick size for price rounding
DEFAULT_TICK_SIZE = 0.01

# Maximum order quantity allowed
MAX_ORDER_QUANTITY = 1_000_000

# Minimum valid price
MIN_PRICE = 0.01


class Side(Enum):
    """Order side: BUY or SELL."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Supported order types."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"
    IOC = "IOC"  # Immediate-or-Cancel


class OrderStatus(Enum):
    """Order lifecycle status."""

    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"


@dataclass
class Order:
    """Represents a single order in the book.

    Attributes:
        order_id: Unique order identifier.
        side: BUY or SELL.
        price: Limit price (0 for market orders).
        quantity: Original order quantity.
        remaining: Unfilled quantity remaining.
        order_type: LIMIT, MARKET, or IOC.
        timestamp: Order creation time.
        status: Current order status.
    """

    order_id: int
    side: Side
    price: float
    quantity: int
    remaining: int
    order_type: OrderType = OrderType.LIMIT
    timestamp: float = 0.0
    status: OrderStatus = OrderStatus.OPEN


@dataclass(frozen=True)
class Trade:
    """Represents a matched trade between two orders.

    Attributes:
        trade_id: Unique trade identifier.
        buy_order_id: ID of the buying order.
        sell_order_id: ID of the selling order.
        price: Execution price.
        quantity: Traded quantity.
        timestamp: Trade execution time.
    """

    trade_id: int
    buy_order_id: int
    sell_order_id: int
    price: float
    quantity: int
    timestamp: float


@dataclass(frozen=True)
class BookLevel:
    """Aggregated price level in the order book.

    Attributes:
        price: Price level.
        quantity: Total quantity at this level.
        order_count: Number of orders at this level.
    """

    price: float
    quantity: int
    order_count: int


class OrderValidationError(ValueError):
    """Raised when an order fails validation."""


class OrderNotFoundError(KeyError):
    """Raised when an order is not found in the book."""


class OrderBook:
    """Price-time priority limit order book with matching engine.

    Maintains sorted bid and ask sides. Incoming orders are matched
    against resting liquidity using price-time priority. Unmatched
    portions of limit orders rest in the book.

    Attributes:
        symbol: Trading instrument symbol.
        tick_size: Minimum price increment.
    """

    def __init__(
        self,
        symbol: str = "SIM",
        tick_size: float = DEFAULT_TICK_SIZE,
    ) -> None:
        """Initialize the order book.

        Args:
            symbol: Trading instrument identifier.
            tick_size: Minimum price increment.

        Raises:
            ValueError: If tick_size <= 0.
        """
        if tick_size <= 0:
            raise ValueError(f"tick_size must be positive, got {tick_size}")

        self.symbol = symbol
        self.tick_size = tick_size

        # Price level -> list of orders (time-sorted)
        self._bids: Dict[float, List[Order]] = defaultdict(list)
        self._asks: Dict[float, List[Order]] = defaultdict(list)

        # Order ID -> Order for fast lookup
        self._orders: Dict[int, Order] = {}

        # Trade history
        self._trades: List[Trade] = []

        # Auto-incrementing IDs
        self._next_order_id = 1
        self._next_trade_id = 1

        logger.info(
            "OrderBook initialized: symbol=%s, tick_size=%s",
            symbol, tick_size,
        )

    @property
    def trades(self) -> List[Trade]:
        """Return list of all executed trades."""
        return list(self._trades)

    @property
    def trade_count(self) -> int:
        """Return total number of executed trades."""
        return len(self._trades)

    @property
    def order_count(self) -> int:
        """Return total number of open orders in the book."""
        return sum(
            1
            for order in self._orders.values()
            if order.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)
        )

    def submit_order(
        self,
        side: Side,
        price: float,
        quantity: int,
        order_type: OrderType = OrderType.LIMIT,
        timestamp: Optional[float] = None,
    ) -> Tuple[Order, List[Trade]]:
        """Submit a new order to the book.

        Args:
            side: BUY or SELL.
            price: Limit price. Ignored for MARKET orders.
            quantity: Number of units to trade.
            order_type: LIMIT, MARKET, or IOC.
            timestamp: Order time. Uses current time if None.

        Returns:
            Tuple of (submitted_order, list_of_trades_generated).

        Raises:
            OrderValidationError: If order parameters are invalid.
        """
        self._validate_order_params(side, price, quantity, order_type)

        if timestamp is None:
            timestamp = time.time()

        order = self._create_order(side, price, quantity, order_type, timestamp)
        self._orders[order.order_id] = order

        trades = self._match_order(order)
        self._handle_post_match(order, order_type)

        logger.debug(
            "Order %d: %s %s %d @ %.2f -> %d trades",
            order.order_id, side.value, order_type.value,
            quantity, price, len(trades),
        )
        return order, trades

    def cancel_order(self, order_id: int) -> Order:
        """Cancel an open order.

        Args:
            order_id: ID of the order to cancel.

        Returns:
            The cancelled order.

        Raises:
            OrderNotFoundError: If order not found.
            OrderValidationError: If order is already filled/cancelled.
        """
        order = self._get_order(order_id)
        self._validate_cancellable(order)

        self._remove_from_book(order)
        order.status = OrderStatus.CANCELLED

        logger.debug("Cancelled order %d", order_id)
        return order

    def get_order(self, order_id: int) -> Order:
        """Look up an order by ID.

        Args:
            order_id: Order identifier.

        Returns:
            The Order object.

        Raises:
            OrderNotFoundError: If not found.
        """
        return self._get_order(order_id)

    def best_bid(self) -> Optional[float]:
        """Return the best (highest) bid price.

        Returns:
            Best bid price, or None if no bids.
        """
        active_prices = self._active_bid_prices()
        return max(active_prices) if active_prices else None

    def best_ask(self) -> Optional[float]:
        """Return the best (lowest) ask price.

        Returns:
            Best ask price, or None if no asks.
        """
        active_prices = self._active_ask_prices()
        return min(active_prices) if active_prices else None

    def get_midprice(self) -> Optional[float]:
        """Calculate the mid-price between best bid and ask.

        Returns:
            Mid-price, or None if either side is empty.
        """
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return None

    def get_spread(self) -> Optional[float]:
        """Calculate the bid-ask spread.

        Returns:
            Spread in price units, or None if either side is empty.
        """
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is not None and ask is not None:
            return ask - bid
        return None

    def get_book_depth(
        self, levels: int = 5
    ) -> Tuple[List[BookLevel], List[BookLevel]]:
        """Get top N price levels for both sides.

        Args:
            levels: Number of price levels to return per side.

        Returns:
            Tuple of (bid_levels, ask_levels), each sorted by price priority.
        """
        bid_levels = self._aggregate_side(self._bids, reverse=True)[:levels]
        ask_levels = self._aggregate_side(self._asks, reverse=False)[:levels]
        return bid_levels, ask_levels

    def get_vwap(self, side: Side, quantity: int) -> Optional[float]:
        """Calculate volume-weighted average price for sweeping quantity.

        Simulates the average fill price if you were to execute a market
        order of the given quantity against the current book.

        Args:
            side: Side of the book to sweep (BUY sweeps asks, SELL sweeps bids).
            quantity: Quantity to sweep.

        Returns:
            VWAP if sufficient liquidity, None otherwise.
        """
        levels = self._get_opposing_levels(side)
        return self._compute_vwap(levels, quantity)

    def _compute_vwap(
        self, levels: List[BookLevel], quantity: int
    ) -> Optional[float]:
        """Compute VWAP across price levels for a given quantity.

        Args:
            levels: Sorted price levels.
            quantity: Target quantity.

        Returns:
            VWAP if sufficient liquidity, None otherwise.
        """
        remaining = quantity
        total_cost = 0.0

        for level in levels:
            fill_qty = min(remaining, level.quantity)
            total_cost += fill_qty * level.price
            remaining -= fill_qty
            if remaining <= 0:
                break

        if remaining > 0:
            return None  # Insufficient liquidity

        return total_cost / quantity

    def _validate_order_params(
        self,
        side: Side,
        price: float,
        quantity: int,
        order_type: OrderType,
    ) -> None:
        """Validate order parameters.

        Args:
            side: Order side.
            price: Order price.
            quantity: Order quantity.
            order_type: Type of order.

        Raises:
            OrderValidationError: If any parameter is invalid.
        """
        if quantity <= 0 or quantity > MAX_ORDER_QUANTITY:
            raise OrderValidationError(
                f"Quantity must be in (0, {MAX_ORDER_QUANTITY}], got {quantity}"
            )
        if order_type != OrderType.MARKET and price < MIN_PRICE:
            raise OrderValidationError(
                f"Price must be >= {MIN_PRICE}, got {price}"
            )

    def _create_order(
        self,
        side: Side,
        price: float,
        quantity: int,
        order_type: OrderType,
        timestamp: float,
    ) -> Order:
        """Create a new Order object with auto-incremented ID.

        Args:
            side: Order side.
            price: Order price.
            quantity: Order quantity.
            order_type: Type of order.
            timestamp: Creation time.

        Returns:
            New Order instance.
        """
        order = Order(
            order_id=self._next_order_id,
            side=side,
            price=price,
            quantity=quantity,
            remaining=quantity,
            order_type=order_type,
            timestamp=timestamp,
        )
        self._next_order_id += 1
        return order

    def _match_order(self, order: Order) -> List[Trade]:
        """Match an incoming order against the resting book.

        Args:
            order: Incoming order to match.

        Returns:
            List of trades generated.
        """
        if order.side == Side.BUY:
            return self._match_buy(order)
        return self._match_sell(order)

    def _match_buy(self, order: Order) -> List[Trade]:
        """Match a buy order against asks.

        Args:
            order: Incoming buy order.

        Returns:
            List of trades.
        """
        trades: List[Trade] = []
        sorted_prices = sorted(self._active_ask_prices())

        for ask_price in sorted_prices:
            if order.remaining <= 0:
                break
            if order.order_type != OrderType.MARKET and ask_price > order.price:
                break
            trades.extend(self._fill_at_price(order, self._asks[ask_price], ask_price))

        self._cleanup_empty_levels(self._asks)
        return trades

    def _match_sell(self, order: Order) -> List[Trade]:
        """Match a sell order against bids.

        Args:
            order: Incoming sell order.

        Returns:
            List of trades.
        """
        trades: List[Trade] = []
        sorted_prices = sorted(self._active_bid_prices(), reverse=True)

        for bid_price in sorted_prices:
            if order.remaining <= 0:
                break
            if order.order_type != OrderType.MARKET and bid_price < order.price:
                break
            trades.extend(self._fill_at_price(order, self._bids[bid_price], bid_price))

        self._cleanup_empty_levels(self._bids)
        return trades

    def _fill_at_price(
        self,
        aggressor: Order,
        resting_orders: List[Order],
        price: float,
    ) -> List[Trade]:
        """Fill an aggressor against resting orders at a price level.

        Args:
            aggressor: Incoming order.
            resting_orders: Orders resting at this price level.
            price: Execution price.

        Returns:
            Trades generated at this level.
        """
        trades: List[Trade] = []
        orders_to_remove: List[Order] = []

        for resting in resting_orders:
            if aggressor.remaining <= 0:
                break

            fill_qty = min(aggressor.remaining, resting.remaining)
            trade = self._execute_trade(aggressor, resting, price, fill_qty)
            trades.append(trade)

            if resting.remaining == 0:
                orders_to_remove.append(resting)

        for order in orders_to_remove:
            resting_orders.remove(order)

        return trades

    def _execute_trade(
        self,
        aggressor: Order,
        resting: Order,
        price: float,
        quantity: int,
    ) -> Trade:
        """Execute a trade between two orders.

        Args:
            aggressor: Incoming order.
            resting: Resting order.
            price: Execution price.
            quantity: Fill quantity.

        Returns:
            The executed Trade.
        """
        aggressor.remaining -= quantity
        resting.remaining -= quantity

        self._update_order_status(aggressor)
        self._update_order_status(resting)

        buy_id = aggressor.order_id if aggressor.side == Side.BUY else resting.order_id
        sell_id = resting.order_id if aggressor.side == Side.BUY else aggressor.order_id

        trade = Trade(
            trade_id=self._next_trade_id,
            buy_order_id=buy_id,
            sell_order_id=sell_id,
            price=price,
            quantity=quantity,
            timestamp=aggressor.timestamp,
        )
        self._next_trade_id += 1
        self._trades.append(trade)
        return trade

    def _update_order_status(self, order: Order) -> None:
        """Update order status based on remaining quantity.

        Args:
            order: Order to update.
        """
        if order.remaining == 0:
            order.status = OrderStatus.FILLED
        elif order.remaining < order.quantity:
            order.status = OrderStatus.PARTIALLY_FILLED

    def _handle_post_match(
        self, order: Order, order_type: OrderType
    ) -> None:
        """Handle order after matching (rest in book or cancel).

        Args:
            order: The order post-matching.
            order_type: Original order type.
        """
        if order.remaining <= 0:
            return

        # IOC and MARKET orders cancel unfilled remainder
        if order_type in (OrderType.IOC, OrderType.MARKET):
            order.status = OrderStatus.CANCELLED
            return

        # LIMIT orders rest in the book
        self._add_to_book(order)

    def _add_to_book(self, order: Order) -> None:
        """Add an order to the appropriate side of the book.

        Args:
            order: Order to add.
        """
        book = self._bids if order.side == Side.BUY else self._asks
        book[order.price].append(order)

    def _remove_from_book(self, order: Order) -> None:
        """Remove an order from the book.

        Args:
            order: Order to remove.
        """
        book = self._bids if order.side == Side.BUY else self._asks
        if order.price in book:
            book[order.price] = [
                o for o in book[order.price] if o.order_id != order.order_id
            ]
            if not book[order.price]:
                del book[order.price]

    def _get_order(self, order_id: int) -> Order:
        """Get order by ID or raise.

        Args:
            order_id: Order identifier.

        Returns:
            The Order.

        Raises:
            OrderNotFoundError: If not found.
        """
        if order_id not in self._orders:
            raise OrderNotFoundError(f"Order {order_id} not found")
        return self._orders[order_id]

    def _validate_cancellable(self, order: Order) -> None:
        """Validate that an order can be cancelled.

        Args:
            order: Order to check.

        Raises:
            OrderValidationError: If order cannot be cancelled.
        """
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            raise OrderValidationError(
                f"Cannot cancel order {order.order_id}: status={order.status.value}"
            )

    def _active_bid_prices(self) -> List[float]:
        """Return bid prices with active orders.

        Returns:
            List of prices with non-empty order lists.
        """
        return [p for p, orders in self._bids.items() if orders]

    def _active_ask_prices(self) -> List[float]:
        """Return ask prices with active orders.

        Returns:
            List of prices with non-empty order lists.
        """
        return [p for p, orders in self._asks.items() if orders]

    def _aggregate_side(
        self,
        side: Dict[float, List[Order]],
        reverse: bool,
    ) -> List[BookLevel]:
        """Aggregate orders by price level.

        Args:
            side: Book side (bids or asks).
            reverse: Sort descending if True.

        Returns:
            Aggregated BookLevel list, sorted by price.
        """
        levels: List[BookLevel] = []
        for price, orders in side.items():
            active = [o for o in orders if o.remaining > 0]
            if active:
                total_qty = sum(o.remaining for o in active)
                levels.append(BookLevel(price, total_qty, len(active)))

        levels.sort(key=lambda lvl: lvl.price, reverse=reverse)
        return levels

    def _get_opposing_levels(self, side: Side) -> List[BookLevel]:
        """Get the opposing side's price levels for VWAP calculation.

        Args:
            side: The aggressor's side (BUY sweeps asks, SELL sweeps bids).

        Returns:
            Sorted BookLevel list of the opposing side.
        """
        if side == Side.BUY:
            return self._aggregate_side(self._asks, reverse=False)
        return self._aggregate_side(self._bids, reverse=True)

    def _cleanup_empty_levels(
        self, side: Dict[float, List[Order]]
    ) -> None:
        """Remove price levels with no remaining orders.

        Args:
            side: Book side to clean.
        """
        empty_prices = [p for p, orders in side.items() if not orders]
        for price in empty_prices:
            del side[price]
