# 📋 PROJECT DEVELOPMENT NOTES

## 🏗️ Unified Dashboard Architecture

### **Current Implementation:**
- **Single Dashboard**: Integrated in `main.py` (lines 600-900)
- **Template Engine**: Jinja2 with FastAPI
- **Data Source**: Unified context dictionary for all dashboard variables
- **No Separate Dashboard Module**: Old `src/dashboard.py` disabled (renamed to `.old`)

### **Key Design Decisions:**
1. **Centralized Route Handling**: All dashboard endpoints in main.py
2. **Single Template**: `dashboard.html` serves all dashboard functionality
3. **Unified Context**: One comprehensive context dictionary
4. **API Integration**: Direct access to all trading engine components

### **Benefits:**
- ✅ **Single Source of Truth**: No duplicate route definitions
- ✅ **Better Performance**: No module import conflicts
- ✅ **Easier Maintenance**: All dashboard logic in one place
- ✅ **Consistent State**: Direct access to trading engine status

---

## 💷 GBP Trading System Architecture

### **Currency Configuration:**
- **Base Currency**: GBP (portfolio valuation, display currency)
- **Quote Currencies**: 8 cryptocurrencies (BTC, ETH, SOL, LTC, DOT, ADA, LINK, UNI)
- **Trading Pairs**: All pairs use GBP as quote currency (e.g., BTC-GBP, ETH-GBP)
- **Risk Management**: GBP-based position sizing and limits

### **Data Flow Architecture:**

#### **Market Data Source (USD → GBP Conversion)**
```
USD Market Data (Rich) → AI Model Signals → Dashboard Display (GBP)
         ↓                          ↓                    ↓
  High Liquidity       Trained on USD    User-friendly GBP
  Real-time Prices     Best Signals      Currency Display
```

#### **Why USD Data Source?**
1. **Market Data Quality**: USD pairs have 531 pairs vs 47 GBP pairs
2. **Liquidity**: USD markets have much higher trading volume
3. **API Reliability**: USD endpoints provide real-time data consistently
4. **AI Model Training**: Historical data and models built on USD markets
5. **Signal Quality**: Better market depth → better trading signals

#### **GBP Display Conversion:**
```python
# Real-time conversion in main.py
usd_price = market_data['BTC-USD']['price']  # $111,059.53
exchange_rate = 1.30  # Current GBP-USD rate
gbp_price = usd_price / exchange_rate  # £85,430.41

# Dashboard shows:
# Pair: BTC-GBP
# Price: £85,430.41
# Source: BTC-USD (high liquidity data)
```

### **Technical Implementation:**

#### **Configuration (settings.py)**
```python
PRODUCT_IDS: list = [
    'BTC-GBP', 'ETH-GBP', 'SOL-GBP', 'LTC-GBP', 
    'DOT-GBP', 'ADA-GBP', 'LINK-GBP', 'UNI-GBP'
]  # 8 GBP pairs for trading

BASE_CURRENCY: str = 'GBP'  # Portfolio valuation
MAX_POSITION_SIZE: float = 0.02  # 2% per trade in GBP
```

#### **Market Data Pipeline (main.py)**
```python
# Lines 718-790: Market conditions processing
usd_pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'LTC-USD']
exchange_rate = coinbase_api.get_product_ticker('GBP-USD')['price']

# Get USD market data (rich data)
for product_id in usd_pairs:
    ticker = coinbase_api.get_product_ticker(product_id)  # Real-time USD
    signal = ai_model.get_signal(product_id)  # USD-trained model
    # Convert to GBP for display
    gbp_price = ticker['price'] / exchange_rate
    gbp_product_id = product_id.replace('-USD', '-GBP')
```

#### **AI Model Training:**
- **Training Data**: Historical USD pair data
- **Signal Generation**: Based on USD market patterns
- **Model Files**: Saved as `{pair}_model.pkl` (e.g., `BTC-USD_model.pkl`)
- **Prediction Targets**: USD price movements
- **Confidence Thresholds**: 60% for trading signals

### **User Experience (GBP Frontend):**

#### **Dashboard Display:**
- **Prices**: Shown in GBP (£85,430.41)
- **Portfolio**: Valued in GBP
- **Trading Limits**: GBP-based (2% of GBP portfolio)
- **Risk Metrics**: GBP P&L calculations
- **Balance Alerts**: GBP thresholds (£10 warning, £5 critical)

#### **Market AI Signals Section:**
```html
<!-- Shows converted data -->
<div class="card">
    <h6><i class="fab fa-bitcoin"></i> BTC-GBP</h6>
    <strong>£85,430.41</strong>
    <small>Data from BTC-USD</small>
    <span class="badge bg-success">BUY</span>
    <small>75.2% Confidence</small>
</div>
```

---

## 🔧 Development Patterns & Best Practices

### **Template Variable Structure:**
```python
# Unified context dictionary in main.py (lines 761-830)
context = {
    # Trading status
    "trading_active": db_manager.get_trading_active(),
    "paper_trading": trading_engine.paper_trading,
    
    # Portfolio metrics  
    "portfolio": converted_portfolio,
    "formatted_total": formatted_total,
    "display_currency": display_currency,
    
    # Market data (converted GBP display)
    "product_ids": [pair.replace('-USD', '-GBP') for pair in usd_pairs],
    "market_conditions": gbp_market_conditions,  # Converted data
    
    # Model information
    "models_info": {
        'models_trained_count': len(model_status['models_trained']),
        'btc_model_ready': model_status['btc_model_ready'],
        # ... all model fields for template compatibility
    },
    
    # GBP-specific features
    "gbp_balance_status": balance_manager.check_gbp_balance(),
}
```

### **Error Handling Strategy:**
```python
# Graceful fallbacks for API failures
try:
    exchange_rate = float(gbp_ticker['price'])
except:
    exchange_rate = 1.30  # Default fallback rate
    
try:
    signal_data = ai_model.get_signal(product_id)
except:
    signal_data = {'confidence': 0, 'action': 'HOLD'}  # Default signal
```

### **Import Organization:**
```python
# Main.py imports (lines 1-50)
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Local imports grouped by module
from config.settings import settings
from src.coinbase_api import coinbase_api
from src.trading_engine import trading_engine
from src.ai_model import ai_model
```

---

## 🚀 Future Development Considerations

### **Scalability Points:**
1. **Multi-Currency Support**: Architecture supports adding EUR, USD display options
2. **Exchange Expansion**: USD→GBP conversion can work with other exchanges
3. **Model Updates**: USD-trained models can be swapped without dashboard changes
4. **Risk Management**: GBP limits easily adjustable via settings

### **Potential Enhancements:**
1. **Real-time Conversion Rates**: WebSocket for GBP-USD rate updates
2. **Historical GBP Analysis**: Backtest strategies with GBP pair availability
3. **Multi-Exchange Data**: Aggregate USD data from multiple exchanges
4. **Advanced GBP Features**: UK market hours, GBP-specific risk factors

### **Maintenance Notes:**
1. **Exchange Rate Monitoring**: Watch for GBP-USD volatility impacts
2. **Model Retraining**: Update USD models when GBP pair data improves
3. **API Deprecation**: Monitor Coinbase API changes for GBP pairs
4. **User Feedback**: Track GBP display preference and conversion clarity

---

## 📚 Key Files & Their Roles

### **Core Dashboard:**
- **`main.py` (600-900)**: Unified dashboard implementation
- **`src/templates/dashboard.html`**: Single dashboard template
- **`config/settings.py`**: GBP configuration and trading pairs

### **Trading System:**
- **`src/trading_engine.py`**: GBP-based position management
- **`src/ai_model.py`**: USD-trained signal generation
- **`src/coinbase_api.py`**: USD market data + GBP conversion
- **`src/risk_manager.py`**: GBP risk calculations

### **Data Management:**
- **`src/database.py`**: Trade storage with GBP valuation
- **`src/data_collector.py`**: USD data collection for AI
- **`src/currency_utils.py`**: GBP conversion utilities

### **Deprecated:**
- **`src/dashboard.py.old`**: Old dashboard implementation (DISABLED)

---

## ⚠️ Important Architecture Notes

### **Why This Architecture Works:**
1. **Best Data Quality**: Leverages superior USD market data
2. **User-Friendly**: Native GBP display for UK users
3. **Future-Proof**: Easy to adapt for other currencies
4. **Maintainable**: Single source of truth for dashboard
5. **Performant**: Minimal data conversion overhead

### **Critical Trade-offs:**
1. **Conversion Risk**: GBP prices depend on USD→GBP rate
2. **Model Mismatch**: AI trained on USD, trading in GBP pairs
3. **User Clarity**: Must explain data source transparently
4. **Complexity**: Conversion layer adds slight complexity

### **Success Metrics:**
- ✅ Dashboard loads without template errors
- ✅ All 8 GBP pairs display with converted data
- ✅ AI signals work with USD market quality
- ✅ Users see familiar GBP prices
- ✅ Trading engine uses GBP risk management

---

## 🔧 Troubleshooting Guide

### **Common Issues & Solutions:**

#### **Empty Market Signals Section:**
- **Cause**: Missing `product_ids` in context or conversion errors
- **Fix**: Check main.py lines 718-790 for USD→GBP conversion logic

#### **Incorrect GBP Prices:**
- **Cause**: Wrong exchange rate or division error
- **Fix**: Verify GBP-USD rate fetch in main.py line 725

#### **Model Training Issues:**
- **Cause**: Trying to train on GBP pairs with no data
- **Fix**: Use USD pairs for training, convert for display

#### **Template Variable Errors:**
- **Cause**: Mismatch between context keys and template references
- **Fix**: Ensure `models_info`, `product_ids`, `gbp_balance_status` in context

### **Development Checklist:**
- [ ] Use USD pairs for AI model training and signals
- [ ] Convert USD prices to GBP for dashboard display
- [ ] Include `product_ids` and `models_info` in context
- [ ] Explain USD data source in UI
- [ ] Test conversion accuracy with real rates
- [ ] Verify all 8 GBP pairs display correctly

---

**Last Updated**: 2026-01-27
**Architecture Status**: ✅ Unified Dashboard + USD→GBP Conversion
**Data Source**: High-liquidity USD markets with GBP display conversion