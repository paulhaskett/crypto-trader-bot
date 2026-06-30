# Crypto Trading Bot - Developer Documentation

Welcome to the crypto trading bot developer documentation.

## Quick Links

- [Architecture](architecture.md) - System design and components
- [API Reference](api-reference.md) - Complete API endpoint documentation
- [Settings Reference](settings.md) - Configuration settings
- [Sessions](sessions/) - Change history by version

---

## System Overview

A GBP-based automated crypto trading system running on Raspberry Pi 5/Docker.

**Key Features**:
- Multi-process architecture (trading + API workers)
- AI-powered signal generation (Random Forest, Neural Network, Gradient Boosting)
- Risk management with scale-in/scale-out
- Web dashboard for monitoring and control
- Paper trading mode for testing

---

## Quick Start

### Development Mode

```bash
# Install dependencies
pip install -r requirements.txt

# Run AI model tests
python tools/test_ai.py
```

### Docker Mode

```bash
# Build and run
docker-compose up --build -d

# View logs
docker-compose logs -f crypto-trader-bot

# Stop
docker-compose down
```

---

## Changelog

| Version | Date | Summary |
|---------|------|---------|
| [v4.0](sessions/v4.0.md) | May 31, 2026 | Models page bugs: agreement matrix N/A fix, auto-retrain fix; API consolidation: removed `/api/trades`, merged `/api/ai/retrain_status` into `/api/models/retrain_progress` |
| [v3.0](sessions/v3.0.md) | May 17, 2026 | AI module refactor into modular architecture, prediction tracking with entry_reason |
| [v2.9.2](sessions/v2.9.0.md) | May 15, 2026 | Configurable vote threshold (75%), dashboard shows both thresholds |
| [v2.9.1](sessions/v2.9.0.md) | May 15, 2026 | Ridge model loading fix, 75% threshold fix, confidence fallback - fixes 0% confidence issue |
| [v2.9.0](sessions/v2.9.0.md) | May 8, 2026 | Fee parsing fix (1.1% vs 1.8%), trailing_activated bug, AI SELL for positions, stop loss direction |
| [v2.9.1](sessions/v2.9.0.md) | May 10, 2026 | Peak price tracking bug fix - added logging to update_peak_price(), added peak_price to initial sync |
| [v2.9.2](sessions/v2.9.0.md) | May 10, 2026 | opened_at date preservation - fixed initial sync to preserve original date, fixed database.py to not overwrite |
| [v2.9.3](sessions/v2.9.0.md) | May 10, 2026 | Real-time peak tracking - peak updates on every API call, not just 4-hour cycle |
| [v2.9.4](sessions/v2.9.0.md) | May 10, 2026 | Fixed trailing stop floor (95% of entry), real-time peak in load_open_positions(), accurate dashboard data |
| [v2.9.5](sessions/v2.9.0.md) | May 10, 2026 | Dashboard performance fix (60s->0.02s), added current_price persistence for new positions |
| [v2.9.6](sessions/v2.9.0.md) | May 12, 2026 | Fixed stale ADA position, enhanced trades API with entry/exit/pnl%, fixed _close_position bug |
| [v2.8.0](sessions/v2.8.0.md) | May 8, 2026 | AI model fixes, stop loss bug fixes, Ridge model integration, trailing stop overhaul |
| [v2.7](sessions/v2.7.md) | Apr 29, 2026 | Trailing stop fix verification, smart scale-in, trades page fixes |
| [v2.6](sessions/v2.6.md) | Apr 27, 2026 | Cache manager refactor, trailing stop sell fix |
| [v2.5](sessions/v2.5.md) | Apr 22, 2026 | Trailing stop fix, AI confidence threshold, agreement % display |
| [v2.4](sessions/v2.4.md) | Apr 17, 2026 | Trailing stop implementation with per-regime percentages |
| [v2.3](sessions/v2.3.md) | Apr 13, 2026 | ATR threshold fix for low volatility |
| [v2.2](sessions/v2.2.md) | Apr 10, 2026 | Configuration refactor, Binance addition |
| [v2.1](sessions/v2.1.md) | Apr 10, 2026 | Initial multi-source pricer, Binance data source |
| [v1.9](sessions/v1.9.0.md) | Mar 22, 2026 | Settings page complete fix |
| [v1.8](sessions/v1.8.0.md) | Mar 21, 2026 | Dashboard & page improvements |

Full history in [docs/sessions/](sessions/).

---

## Troubleshooting

### Dashboard Loading Slowly
- Check signal cache: `data/signal_cache.json`
- Check database size: `ls -lh data/trades.db`
- Review logs: `docker-compose logs`

### Trading Not Executing
- Check trading active: GET `/api/status`
- Check GBP balance: GET `/api/gbp-balance`
- Check AI models: GET `/api/models/status`

### API Errors
- Verify endpoints exist: `docs/api-reference.md`
- Check API worker logs: `docker-compose logs`
- Test endpoint manually: `curl http://localhost:8000/api/status`

---

## File Structure

```
crypto-trader-bot/
├── config/              # Configuration
│   ├── settings.py     # Settings class
│   └── api_keys.env    # API keys (not committed)
├── src/                # Core modules
│   ├── startup.py      # Process orchestration
│   ├── trading_loop.py # Trading scheduler
│   ├── trading_engine.py # Trading logic
│   ├── ai_model.py     # ML (wrapper - imports from src/ai/)
│   ├── ai/             # NEW: Modular AI package
│   │   ├── __init__.py # Exports + backward-compat AIModel
│   │   ├── base.py     # Core utilities, types, logging
│   │   ├── regime.py  # Market regime detection
│   │   ├── features.py # Feature engineering
│   │   ├── evaluation.py # Performance metrics
│   │   ├── ensemble.py # Model voting
│   │   ├── models.py   # Model storage/loading
│   │   ├── training.py # Model training
│   │   └── signals.py # Signal generation
│   ├── risk_manager.py # Risk
│   ├── database.py     # Persistence
│   ├── coinbase_api.py # Exchange
│   └── templates/      # HTML pages
├── data/               # Runtime data
│   ├── trades.db       # SQLite
│   └── signal_cache.json # Signal cache
├── docs/               # This documentation
├── migrations/         # DB migrations
├── tools/              # Debug and test utilities
├── backup/             # Legacy backup files
├── main_legacy.py      # DEPRECATED (old dev mode)
└── requirements.txt    # Dependencies
```

---

## Contributing

1. Document changes in session file
2. Update relevant docs (api-reference, settings, architecture)
3. Run linting and type checks
4. Test in paper trading mode first
5. Rebuild Docker container for production
