"""Tests for runtime trading-setting validation."""

import pytest

from config.settings import Settings


def make_settings():
    return Settings.__new__(Settings)


def test_safe_runtime_values_are_accepted():
    settings = make_settings()
    settings.validate_runtime_values({
        'MODEL_CONFIDENCE_THRESHOLD': 0.8,
        'STOP_LOSS_MIN_PERCENT': 0.1,
        'MAX_POSITION_SIZE': 0.25,
        'MAX_CONCURRENT_POSITIONS': 2,
        'MARKET_CHECK_INTERVAL': 3600,
        'DISPLAY_CURRENCY': 'GBP',
        'TAKE_PROFIT_LEVELS': [0.02, 0.04, 0.06],
    })


def test_unsafe_runtime_values_are_rejected():
    settings = make_settings()
    for key, value in [
        ('MODEL_CONFIDENCE_THRESHOLD', 1.5),
        ('STOP_LOSS_MIN_PERCENT', -0.1),
        ('MAX_POSITION_SIZE', 0.75),
        ('MAX_CONCURRENT_POSITIONS', 0),
        ('MARKET_CHECK_INTERVAL', 10),
        ('DISPLAY_CURRENCY', 'EUR'),
        ('TAKE_PROFIT_LEVELS', [-0.02, 0.04, 0.06]),
    ]:
        with pytest.raises(ValueError):
            settings.validate_runtime_values({key: value})
