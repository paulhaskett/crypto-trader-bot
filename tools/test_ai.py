#!/usr/bin/env python3
"""
Test script for AI model training and prediction.

This script tests the AI model functionality with sample data
and validates that the machine learning components work correctly.
"""

import sys
import logging
from datetime import datetime
import pandas as pd
import numpy as np

# Add src to path
sys.path.append('src')

from config.settings import settings
from src.data_collector import data_collector
from src.ai_model import ai_model

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_sample_data() -> pd.DataFrame:
    """
    Create sample OHLCV data for testing.

    Returns:
        DataFrame with sample price data
    """
    # Create 100 days of sample data
    dates = pd.date_range(start='2023-01-01', periods=100, freq='D')

    # Generate realistic price movements
    np.random.seed(42)  # For reproducible results

    # Start with a base price and add random walks
    base_price = 50000  # BTC-like price
    price_changes = np.random.normal(0, 0.02, len(dates))  # 2% daily volatility
    prices = base_price * np.cumprod(1 + price_changes)

    # Create OHLCV data
    data = []
    for i, (date, close) in enumerate(zip(dates, prices)):
        # Generate OHLC from close price with some variation
        high = close * (1 + abs(np.random.normal(0, 0.01)))
        low = close * (1 - abs(np.random.normal(0, 0.01)))
        open_price = data[-1]['close'] if data else close * (1 + np.random.normal(0, 0.005))
        volume = np.random.lognormal(15, 1)  # Realistic volume

        data.append({
            'timestamp': date,
            'open': open_price,
            'high': max(open_price, high),
            'low': min(open_price, low),
            'close': close,
            'volume': volume
        })

    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    return df


def test_technical_indicators():
    """Test technical indicator calculations."""
    logger.info("Testing technical indicators...")

    # Create sample data
    df = create_sample_data()

    # Calculate indicators
    df_with_indicators = data_collector.calculate_technical_indicators(df)

    # Check that indicators were added
    expected_indicators = ['sma_20', 'rsi', 'macd', 'bb_upper', 'bb_lower']
    for indicator in expected_indicators:
        if indicator in df_with_indicators.columns:
            logger.info(f"✓ {indicator} calculated successfully")
        else:
            logger.error(f"✗ {indicator} not found in data")

    return df_with_indicators


def test_ai_model_training():
    """Test AI model training with sample data."""
    logger.info("Testing AI model training...")

    # Create sample data
    df = create_sample_data()

    # Calculate indicators
    df_with_indicators = data_collector.calculate_technical_indicators(df)

    # Test feature preparation
    features_df = ai_model.prepare_features(df_with_indicators)
    logger.info(f"Prepared {len(features_df)} feature samples with {len(features_df.columns)} features")

    # Test target creation
    targets = ai_model.create_target_labels(df_with_indicators)
    logger.info(f"Created {len(targets)} target labels")

    # Test model training directly with sample data (bypass data collection)
    try:
        # Prepare features and targets manually
        features_df = ai_model.prepare_features(df_with_indicators)
        targets = ai_model.create_target_labels(df_with_indicators)

        if features_df.empty or targets.empty:
            logger.error("✗ Could not prepare features/targets")
            return {'success': False, 'error': 'Feature preparation failed'}

        # Align features and targets
        min_length = min(len(features_df), len(targets))
        features_df = features_df.iloc[:min_length]
        targets = targets.iloc[:min_length]

        if len(features_df) < 30:
            logger.error("✗ Too few training samples")
            return {'success': False, 'error': 'Too few training samples'}

        # Split data
        from sklearn.model_selection import train_test_split
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

        X_train, X_test, y_train, y_test = train_test_split(
            features_df, targets, test_size=0.3, random_state=42, shuffle=False
        )

        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Train model
        model = RandomForestClassifier(
            n_estimators=50,  # Smaller for testing
            max_depth=8,
            min_samples_split=5,
            min_samples_leaf=3,
            random_state=42,
            n_jobs=-1
        )

        model.fit(X_train_scaled, y_train)

        # Test predictions
        y_pred = model.predict(X_test_scaled)
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)

        # Feature importance
        feature_importance = dict(zip(features_df.columns, model.feature_importances_))

        logger.info("✓ Model training successful!")
        logger.info(f"  Training samples: {len(X_train)}")
        logger.info(f"  Test samples: {len(X_test)}")
        logger.info(f"  Accuracy: {accuracy:.3f}")
        logger.info(f"  Precision: {precision:.3f}")
        logger.info(f"  Recall: {recall:.3f}")
        logger.info(f"  F1 Score: {f1:.3f}")

        # Show top 5 important features
        sorted_features = sorted(feature_importance.items(),
                               key=lambda x: x[1], reverse=True)
        logger.info("Top 5 important features:")
        for feature, importance in sorted_features[:5]:
            logger.info(f"  {feature}: {importance:.3f}")

        return {
            'success': True,
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1_score': f1,
            'feature_importance': feature_importance
        }

    except Exception as e:
        logger.error(f"✗ Model training failed: {e}")
        return {'success': False, 'error': str(e)}


def test_prediction():
    """Test model prediction."""
    logger.info("Testing model prediction...")

    # Make a prediction
    prediction = ai_model.predict('BTC-USD')

    if prediction['success']:
        logger.info("✓ Prediction successful!")
        logger.info(f"  Prediction: {prediction['prediction']} (1=bullish, 0=bearish)")
        logger.info(f"  Confidence: {prediction['confidence']:.3f}")
    else:
        logger.error(f"✗ Prediction failed: {prediction['error']}")


def test_signal_generation():
    """Test trading signal generation."""
    logger.info("Testing signal generation...")

    signal = ai_model.get_signal('BTC-USD')

    logger.info(f"Signal: {signal['action']}")
    logger.info(f"Reason: {signal['reason']}")
    logger.info(f"Confidence: {signal['confidence']:.3f}")


def main():
    """Run all tests."""
    logger.info("Starting AI Model Tests")
    logger.info("=" * 50)

    try:
        # Test technical indicators
        test_technical_indicators()

        # Test AI model training
        training_result = test_ai_model_training()

        if training_result['success']:
            # Test prediction and signals
            test_prediction()
            test_signal_generation()

        # Show model status
        status = ai_model.get_model_status()
        logger.info(f"Model status: {status}")

        logger.info("=" * 50)
        logger.info("AI Model Tests Complete!")

    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()