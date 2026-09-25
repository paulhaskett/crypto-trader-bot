from src.coinbase_api import CoinbaseAPI


def test_parse_current_coinbase_filled_order():
    result = CoinbaseAPI._normalise_order_fill({
        "order_id": "order-1",
        "status": "FILLED",
        "filled_size": "0.17",
        "average_filled_price": "91.05",
        "total_fees": "0.0773925",
    })

    assert result == {
        "success": True,
        "order_id": "order-1",
        "status": "FILLED",
        "size": 0.17,
        "price": 91.05,
        "fees": 0.0773925,
    }


def test_parse_current_order_derives_price_from_filled_value():
    result = CoinbaseAPI._normalise_order_fill({
        "order_id": "order-2",
        "status": "FILLED",
        "filled_size": "2",
        "filled_value": "20",
        "total_fees": "0.1",
    })

    assert result["success"] is True
    assert result["size"] == 2.0
    assert result["price"] == 10.0


def test_parse_legacy_coinbase_filled_order():
    result = CoinbaseAPI._normalise_order_fill({
        "order_id": "order-3",
        "status": "FILLED",
        "filled_base_volume": "0.5",
        "total_value": {"value": "25"},
        "total_fees": "0.2",
    })

    assert result["success"] is True
    assert result["size"] == 0.5
    assert result["price"] == 50.0


def test_parse_cancelled_order_is_not_successful():
    result = CoinbaseAPI._normalise_order_fill({
        "order_id": "order-4",
        "status": "CANCELLED",
        "filled_size": "0",
    })

    assert result["success"] is False
    assert result["status"] == "CANCELLED"


def test_parse_open_order_without_fill_is_not_successful():
    result = CoinbaseAPI._normalise_order_fill({
        "order_id": "order-5",
        "status": "OPEN",
        "filled_size": "0",
    })

    assert result["success"] is False
    assert result["status"] == "OPEN"


def test_parse_filled_order_without_verified_price_is_not_successful():
    result = CoinbaseAPI._normalise_order_fill({
        "order_id": "order-6",
        "status": "FILLED",
        "filled_size": "0.17",
    })

    assert result["success"] is False
    assert result["size"] == 0.17
    assert result["price"] == 0.0


def test_parse_unknown_status_is_not_successful_even_with_numbers():
    result = CoinbaseAPI._normalise_order_fill({
        "order_id": "order-7",
        "status": "FAILED",
        "filled_size": "0.17",
        "average_filled_price": "91.05",
    })

    assert result["success"] is False
