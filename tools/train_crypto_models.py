#!/usr/bin/env python3
"""
Script to train AI models for all crypto trading pairs.
"""

import sys
import logging
sys.path.append('src')

from config.settings import settings
from src.ai_model import ai_model

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def train_all_models():
    """Train models for all configured trading pairs."""
    logger.info(f"Starting training for {len(settings.PRODUCT_IDS)} crypto pairs")

    results = {}
    for product_id in settings.PRODUCT_IDS:
        logger.info(f"Training model for {product_id}")
        try:
            result = ai_model.train_model(product_id)
            results[product_id] = result
            if result.get('success'):
                logger.info(f"✅ Successfully trained model for {product_id}")
            else:
                logger.error(f"❌ Failed to train model for {product_id}: {result.get('error')}")
        except Exception as e:
            logger.error(f"❌ Exception training model for {product_id}: {e}")
            results[product_id] = {'success': False, 'error': str(e)}

    # Summary
    successful = sum(1 for r in results.values() if r.get('success'))
    logger.info(f"Training complete: {successful}/{len(settings.PRODUCT_IDS)} models trained successfully")

    return results

if __name__ == "__main__":
    train_all_models()