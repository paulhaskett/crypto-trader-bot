"""
Test script for multi-source market data integration.

Tests the price aggregation from Coinbase, CoinGecko, and Kraken.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_price_mapper():
    """Test price mapper coin ID translations."""
    print("\n" + "="*60)
    print("Testing Price Mapper")
    print("="*60)
    
    from src.price_mapper import get_price_mapper
    
    mapper = get_price_mapper()
    
    test_cases = [
        ('BTC-GBP', 'bitcoin', 'XBTGBP'),
        ('ETH-GBP', 'ethereum', 'ETHGBP'),
        ('SOL-GBP', 'solana', 'SOLGBP'),
    ]
    
    for product_id, expected_cg, expected_kraken in test_cases:
        cg_id = mapper.get_coingecko_id(product_id)
        kraken_pair = mapper.get_kraken_pair(product_id)
        
        print(f"\n{product_id}:")
        print(f"  CoinGecko: {cg_id} (expected: {expected_cg}) {'✓' if cg_id == expected_cg else '✗'}")
        print(f"  Kraken: {kraken_pair} (expected: {expected_kraken}) {'✓' if kraken_pair == expected_kraken else '✗'}")


def test_coingecko_api():
    """Test CoinGecko API integration."""
    print("\n" + "="*60)
    print("Testing CoinGecko API")
    print("="*60)
    
    from src.coingecko_api import get_coingecko_api
    
    cg = get_coingecko_api()
    
    # Test single price
    result = cg.get_price('bitcoin', 'gbp')
    print(f"\nBitcoin GBP price: {result}")
    
    # Test batch prices
    coins = ['bitcoin', 'ethereum', 'solana']
    batch = cg.get_prices_batch(coins, ['gbp', 'usd'])
    print(f"\nBatch prices: {batch}")


def test_kraken_api():
    """Test Kraken API integration."""
    print("\n" + "="*60)
    print("Testing Kraken API")
    print("="*60)
    
    from src.kraken_api import get_kraken_api
    
    kraken = get_kraken_api()
    
    # Test ticker
    ticker = kraken.get_ticker_price('BTC-GBP')
    print(f"\nBTC-GBP ticker: {ticker}")
    
    # Test supported pairs
    supported = kraken.get_supported_products()
    print(f"\nSupported products: {supported[:5]}...")


def test_multi_source_pricer():
    """Test multi-source price aggregator."""
    print("\n" + "="*60)
    print("Testing Multi-Source Price Aggregator")
    print("="*60)
    
    from src.multi_source_pricer import get_multi_source_pricer
    
    pricer = get_multi_source_pricer()
    
    # Test consensus for single product
    try:
        result = pricer.get_consensus_price('BTC-GBP', use_cache=False)
        print(f"\nBTC-GBP Consensus:")
        print(f"  Price: £{result.price:.2f}")
        print(f"  Sources: {result.sources_used}")
        print(f"  Confidence: {result.confidence:.1%}")
        print(f"  Outliers: {result.outlier_sources}")
        print(f"  Max Deviation: {result.max_deviation_pct:.2%}")
    except Exception as e:
        print(f"\nBTC-GBP failed: {e}")
    
    # Test batch
    products = ['BTC-GBP', 'ETH-GBP', 'LTC-GBP']
    try:
        batch_results = pricer.get_batch_prices(products)
        print(f"\nBatch Results:")
        for pid, res in batch_results.items():
            print(f"  {pid}: £{res.price:.2f} (conf: {res.confidence:.0%}, sources: {len(res.sources_used)})")
    except Exception as e:
        print(f"\nBatch failed: {e}")


def test_data_collector():
    """Test data collector with multi-source pricing."""
    print("\n" + "="*60)
    print("Testing Data Collector Integration")
    print("="*60)
    
    from src.data_collector import DataCollector
    
    collector = DataCollector()
    
    # Test prices
    prices = collector.get_current_prices()
    
    print(f"\nCollected prices:")
    for product_id, price in prices.items():
        if 'USD' not in product_id:  # Only show main pairs
            print(f"  {product_id}: £{price:.2f}")


def test_chainlink_verification():
    """Test Chainlink price verification."""
    print("\n" + "="*60)
    print("Testing Chainlink Verification")
    print("="*60)
    
    from src.chainlink_oracle import get_chainlink_oracle
    
    oracle = get_chainlink_oracle()
    
    # Test verification
    result = oracle.verify_price('BTC-GBP', 42000, 'coinbase', tolerance=0.05)
    print(f"\nVerification result:")
    print(f"  Verified: {result.get('verified')}")
    print(f"  Reason: {result.get('reason')}")
    print(f"  Deviation: {result.get('deviation')}")


if __name__ == '__main__':
    print("\n" + "#"*60)
    print("# MULTI-SOURCE MARKET DATA TESTS")
    print("#"*60)
    
    try:
        test_price_mapper()
    except Exception as e:
        print(f"Price mapper test failed: {e}")
    
    try:
        test_coingecko_api()
    except Exception as e:
        print(f"CoinGecko test failed: {e}")
    
    try:
        test_kraken_api()
    except Exception as e:
        print(f"Kraken test failed: {e}")
    
    try:
        test_multi_source_pricer()
    except Exception as e:
        print(f"Multi-source test failed: {e}")
    
    try:
        test_data_collector()
    except Exception as e:
        print(f"Data collector test failed: {e}")
    
    try:
        test_chainlink_verification()
    except Exception as e:
        print(f"Chainlink test failed: {e}")
    
    print("\n" + "#"*60)
    print("# TESTS COMPLETE")
    print("#"*60)
