"""Tests for the limit order book simulator and matching engine."""

import pytest

from orderbook_simulator.orderbook import (
    OrderBook,
    Order,
    Trade,
    BookLevel,
    Side,
    OrderType,
    OrderStatus,
    OrderValidationError,
    OrderNotFoundError,
)


@pytest.fixture
def book() -> OrderBook:
    """Create a fresh order book."""
    return OrderBook(symbol="TEST", tick_size=0.01)


class TestOrderBookInit:
    """Tests for OrderBook initialization."""

    def test_default_init(self) -> None:
        """Default book initializes with no orders."""
        book = OrderBook()
        assert book.symbol == "SIM"
        assert book.order_count == 0
        assert book.trade_count == 0

    def test_custom_tick_size(self) -> None:
        """Custom tick size is stored correctly."""
        book = OrderBook(tick_size=0.05)
        assert book.tick_size == 0.05

    def test_invalid_tick_size_raises(self) -> None:
        """Non-positive tick size raises ValueError."""
        with pytest.raises(ValueError, match="tick_size"):
            OrderBook(tick_size=0)


class TestLimitOrders:
    """Tests for limit order submission and resting."""

    def test_submit_limit_buy(self, book: OrderBook) -> None:
        """A limit buy with no opposing orders rests in the book."""
        order, trades = book.submit_order(
            Side.BUY, price=100.0, quantity=10
        )

        assert order.status == OrderStatus.OPEN
        assert order.remaining == 10
        assert trades == []
        assert book.best_bid() == 100.0

    def test_submit_limit_sell(self, book: OrderBook) -> None:
        """A limit sell with no opposing orders rests in the book."""
        order, trades = book.submit_order(
            Side.SELL, price=101.0, quantity=5
        )

        assert order.status == OrderStatus.OPEN
        assert book.best_ask() == 101.0

    def test_limit_orders_maintain_price_priority(
        self, book: OrderBook
    ) -> None:
        """Best bid is the highest bid; best ask is the lowest ask."""
        book.submit_order(Side.BUY, price=99.0, quantity=10)
        book.submit_order(Side.BUY, price=100.0, quantity=10)
        book.submit_order(Side.SELL, price=102.0, quantity=10)
        book.submit_order(Side.SELL, price=101.0, quantity=10)

        assert book.best_bid() == 100.0
        assert book.best_ask() == 101.0

    def test_full_fill_limit_order(self, book: OrderBook) -> None:
        """A crossing limit order fills completely."""
        book.submit_order(Side.SELL, price=100.0, quantity=10)
        order, trades = book.submit_order(
            Side.BUY, price=100.0, quantity=10
        )

        assert order.status == OrderStatus.FILLED
        assert order.remaining == 0
        assert len(trades) == 1
        assert trades[0].quantity == 10
        assert trades[0].price == 100.0

    def test_partial_fill_limit_order(self, book: OrderBook) -> None:
        """Partial fill leaves remainder resting in book."""
        book.submit_order(Side.SELL, price=100.0, quantity=5)
        order, trades = book.submit_order(
            Side.BUY, price=100.0, quantity=10
        )

        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.remaining == 5
        assert len(trades) == 1
        assert trades[0].quantity == 5

    def test_price_time_priority(self, book: OrderBook) -> None:
        """Earlier orders at the same price are filled first."""
        book.submit_order(Side.SELL, price=100.0, quantity=5, timestamp=1.0)
        book.submit_order(Side.SELL, price=100.0, quantity=5, timestamp=2.0)

        order, trades = book.submit_order(
            Side.BUY, price=100.0, quantity=5, timestamp=3.0
        )

        assert len(trades) == 1
        # First sell order (ID=1) should be filled first
        assert trades[0].sell_order_id == 1


class TestMarketOrders:
    """Tests for market order execution."""

    def test_market_buy_fills_at_best_ask(self, book: OrderBook) -> None:
        """Market buy fills at the best available ask price."""
        book.submit_order(Side.SELL, price=101.0, quantity=10)
        order, trades = book.submit_order(
            Side.BUY, price=0.0, quantity=5, order_type=OrderType.MARKET
        )

        assert order.status == OrderStatus.FILLED
        assert trades[0].price == 101.0

    def test_market_sell_fills_at_best_bid(self, book: OrderBook) -> None:
        """Market sell fills at the best available bid price."""
        book.submit_order(Side.BUY, price=99.0, quantity=10)
        order, trades = book.submit_order(
            Side.SELL, price=0.0, quantity=5, order_type=OrderType.MARKET
        )

        assert order.status == OrderStatus.FILLED
        assert trades[0].price == 99.0

    def test_market_order_sweeps_multiple_levels(
        self, book: OrderBook
    ) -> None:
        """Market order sweeps through multiple price levels."""
        book.submit_order(Side.SELL, price=100.0, quantity=5)
        book.submit_order(Side.SELL, price=101.0, quantity=5)

        order, trades = book.submit_order(
            Side.BUY, price=0.0, quantity=8, order_type=OrderType.MARKET
        )

        assert order.status == OrderStatus.FILLED
        assert len(trades) == 2
        assert trades[0].price == 100.0
        assert trades[0].quantity == 5
        assert trades[1].price == 101.0
        assert trades[1].quantity == 3

    def test_market_order_no_liquidity_cancels(
        self, book: OrderBook
    ) -> None:
        """Market order with no opposing liquidity is cancelled."""
        order, trades = book.submit_order(
            Side.BUY, price=0.0, quantity=10, order_type=OrderType.MARKET
        )

        assert order.status == OrderStatus.CANCELLED
        assert trades == []


class TestIOCOrders:
    """Tests for immediate-or-cancel orders."""

    def test_ioc_fills_available_cancels_rest(
        self, book: OrderBook
    ) -> None:
        """IOC fills what's available and cancels the remainder."""
        book.submit_order(Side.SELL, price=100.0, quantity=5)
        order, trades = book.submit_order(
            Side.BUY, price=100.0, quantity=10, order_type=OrderType.IOC
        )

        assert order.status == OrderStatus.CANCELLED
        assert order.remaining == 5  # Unfilled portion
        assert len(trades) == 1
        assert trades[0].quantity == 5

    def test_ioc_no_match_cancels_immediately(
        self, book: OrderBook
    ) -> None:
        """IOC with no matching liquidity is cancelled entirely."""
        order, trades = book.submit_order(
            Side.BUY, price=99.0, quantity=10, order_type=OrderType.IOC
        )

        assert order.status == OrderStatus.CANCELLED
        assert trades == []


class TestCancelOrder:
    """Tests for order cancellation."""

    def test_cancel_open_order(self, book: OrderBook) -> None:
        """Open orders can be cancelled."""
        order, _ = book.submit_order(Side.BUY, price=100.0, quantity=10)
        cancelled = book.cancel_order(order.order_id)

        assert cancelled.status == OrderStatus.CANCELLED
        assert book.best_bid() is None

    def test_cancel_filled_order_raises(self, book: OrderBook) -> None:
        """Cancelling a filled order raises an error."""
        book.submit_order(Side.SELL, price=100.0, quantity=10)
        order, _ = book.submit_order(Side.BUY, price=100.0, quantity=10)

        with pytest.raises(OrderValidationError, match="Cannot cancel"):
            book.cancel_order(order.order_id)

    def test_cancel_nonexistent_raises(self, book: OrderBook) -> None:
        """Cancelling a non-existent order raises OrderNotFoundError."""
        with pytest.raises(OrderNotFoundError):
            book.cancel_order(99999)


class TestBookState:
    """Tests for book state queries."""

    def test_midprice(self, book: OrderBook) -> None:
        """Mid-price is the average of best bid and ask."""
        book.submit_order(Side.BUY, price=99.0, quantity=10)
        book.submit_order(Side.SELL, price=101.0, quantity=10)

        assert book.get_midprice() == 100.0

    def test_spread(self, book: OrderBook) -> None:
        """Spread is the difference between best ask and bid."""
        book.submit_order(Side.BUY, price=99.0, quantity=10)
        book.submit_order(Side.SELL, price=101.0, quantity=10)

        assert book.get_spread() == 2.0

    def test_empty_book_midprice(self, book: OrderBook) -> None:
        """Mid-price is None for empty book."""
        assert book.get_midprice() is None

    def test_empty_book_spread(self, book: OrderBook) -> None:
        """Spread is None for empty book."""
        assert book.get_spread() is None

    def test_book_depth(self, book: OrderBook) -> None:
        """Book depth returns aggregated price levels."""
        book.submit_order(Side.BUY, price=100.0, quantity=10)
        book.submit_order(Side.BUY, price=100.0, quantity=5)
        book.submit_order(Side.BUY, price=99.0, quantity=20)
        book.submit_order(Side.SELL, price=101.0, quantity=15)

        bids, asks = book.get_book_depth(levels=5)

        assert len(bids) == 2
        assert bids[0].price == 100.0
        assert bids[0].quantity == 15  # 10 + 5
        assert bids[0].order_count == 2
        assert bids[1].price == 99.0
        assert len(asks) == 1

    def test_vwap_calculation(self, book: OrderBook) -> None:
        """VWAP sweeps through levels correctly."""
        book.submit_order(Side.SELL, price=100.0, quantity=10)
        book.submit_order(Side.SELL, price=101.0, quantity=10)

        vwap = book.get_vwap(Side.BUY, quantity=15)

        # 10 @ 100 + 5 @ 101 = 1505 / 15 ~ 100.333
        expected = (10 * 100.0 + 5 * 101.0) / 15
        assert vwap is not None
        assert abs(vwap - expected) < 0.01

    def test_vwap_insufficient_liquidity(self, book: OrderBook) -> None:
        """VWAP returns None when liquidity is insufficient."""
        book.submit_order(Side.SELL, price=100.0, quantity=5)

        assert book.get_vwap(Side.BUY, quantity=100) is None


class TestOrderValidation:
    """Tests for order input validation."""

    def test_zero_quantity_raises(self, book: OrderBook) -> None:
        """Zero quantity raises validation error."""
        with pytest.raises(OrderValidationError, match="Quantity"):
            book.submit_order(Side.BUY, price=100.0, quantity=0)

    def test_negative_quantity_raises(self, book: OrderBook) -> None:
        """Negative quantity raises validation error."""
        with pytest.raises(OrderValidationError, match="Quantity"):
            book.submit_order(Side.BUY, price=100.0, quantity=-5)

    @pytest.mark.parametrize("price", [0.0, -1.0, 0.001])
    def test_invalid_price_raises(
        self, book: OrderBook, price: float
    ) -> None:
        """Below-minimum prices raise validation error for limit orders."""
        with pytest.raises(OrderValidationError, match="Price"):
            book.submit_order(Side.BUY, price=price, quantity=10)

    def test_get_order_by_id(self, book: OrderBook) -> None:
        """Orders can be retrieved by ID."""
        order, _ = book.submit_order(Side.BUY, price=100.0, quantity=10)
        retrieved = book.get_order(order.order_id)

        assert retrieved.order_id == order.order_id
        assert retrieved.price == 100.0
