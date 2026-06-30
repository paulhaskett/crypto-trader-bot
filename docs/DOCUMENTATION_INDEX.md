# 📚 PROJECT DOCUMENTATION SUMMARY

## **Quick Reference Guide**

This document provides an overview of all documentation files and their purpose for developers working on the Crypto Trading Bot project.

---

## **Core Documentation Files**

### **1. README.md** - User & Developer Guide
**Purpose**: Main project documentation for users and developers

**Contents:**
- Project overview and features
- Quick start guide (Docker & Local)
- Configuration settings
- API documentation
- Troubleshooting guide
- Development workflow
- Recent updates (v1.0.6)

**Target Audience**: Users, Developers, Contributors

**Key Sections:**
- Prerequisites & Installation
- Configuration (API keys, trading settings)
- Web Dashboard features
- API endpoints
- Docker deployment
- Safety features
- Recent updates section (v1.0.6 fixes)

---

### **2. AGENTS.md** - AI/Code Assistant Guidelines
**Purpose**: Guidelines for AI assistants and developers working on the project

**Contents:**
- Project overview (Python 3.13+, FastAPI, Docker)
- Build/Integration/Test commands
- Code style guidelines
- Import organization
- File structure
- Testing guidelines
- Configuration management
- Security & Performance
- Recent fixes & updates (v1.0.1 - v1.0.6)
- Coinbase SDK usage guide

**Target Audience**: AI Assistants, Code Reviewers, Developers

**Key Sections:**
- Development setup commands
- Code quality commands (black, mypy, flake8)
- Import organization patterns
- File structure reference
- Naming conventions
- Type hints & error handling
- Testing strategy
- Critical bug fixes history
- Current status summary

**Important Notes for Agents:**
- Always run `docker compose build --no-cache` for code changes
- Use paper trading mode for development
- Check `/api/check-api-permissions` for API issues
- All 8 GBP pairs active and monitored
- Ultra-conservative risk management (1% per trade)

---

### **3. docs/DEVELOPMENT_NOTES.md** - Architecture & Design
**Purpose**: Technical architecture documentation and development patterns

**Contents:**
- Unified Dashboard Architecture (single dashboard in main.py)
- GBP Trading System Architecture (USD → GBP conversion)
- Data flow architecture (USD market data → AI signals → GBP display)
- Technical implementation details
- Development patterns & best practices
- Template variable structure
- Error handling strategy
- Import organization
- Future development considerations
- Key files & their roles
- Troubleshooting guide
- Development checklist

**Target Audience**: Developers, Architects, Maintainers

**Key Sections:**
- Unified dashboard design decisions
- GBP currency configuration
- Why USD data source (market quality, liquidity, API reliability)
- Real-time GBP conversion pipeline
- AI model training details
- User experience (GBP frontend)
- Project structure reference
- Common issues & solutions
- Development checklist

**Critical Architecture Notes:**
- All 8 GBP pairs use USD market data for better liquidity
- Dashboard shows GBP prices with real-time USD → GBP conversion
- Single source of truth for dashboard (main.py)
- No separate dashboard module (old src/dashboard.py disabled)

---

### **4. docs/DEVELOPMENT_HISTORY.md** - Change Log & Fixes
**Purpose**: Detailed history of fixes, improvements, and changes

**Contents:**
- January 2026 - Recent fixes & improvements
- January 27, 2026 - Critical bug fixes (currency switcher, market conditions, route ordering, UI layout)
- December 2025 - January 2026 - Major features
- Known issues & limitations
- Future enhancements
- Deployment notes
- API endpoints status
- Code quality & maintenance
- Testing & validation checklist

**Target Audience**: Developers, Maintainers, QA

**Key Sections:**
- Detailed fix descriptions with root cause and impact
- Code snippets showing before/after
- Log evidence for debugging
- Verification steps for each fix
- Current project status
- Testing checklists
- Manual testing procedures

**Recent Fixes (v1.0.6):**
1. Currency switcher persistence (added `await` to async calls)
2. Market conditions data display (removed invalid GBP-USD ticker)
3. API route ordering (moved specific endpoints before catch-all)
4. UI layout improvement (crypto balance under price)

---

### **5. IMPLEMENTATION_STATUS.md** - Project Completion Status
**Purpose**: Track project implementation phases and completion status

**Contents:**
- Phase 2 completion status
- Memory cgroup implementation results
- Container verification
- System readiness for multi-project deployment

**Target Audience**: System Administrators, DevOps, Maintainers

**Key Sections:**
- Reboot successful verification
- Memory controller status
- Container rebuild completion
- Memory limits working
- Docker warnings resolved
- Multi-project foundation ready

**Current Status:**
- ✅ Memory cgroup implementation complete
- ✅ Docker memory warnings eliminated
- ✅ Container memory limits functional
- ✅ Multi-project foundation ready
- ✅ Trading bot operational

---

## **Documentation Usage Guide**

### **For New Developers**
1. **Start with**: `README.md` - Overview and quick start
2. **Then read**: `AGENTS.md` - Development patterns and code style
3. **Deep dive**: `docs/DEVELOPMENT_NOTES.md` - Architecture and design

### **For Bug Fixing**
1. **Check**: `docs/DEVELOPMENT_HISTORY.md` - Similar issues and solutions
2. **Reference**: `AGENTS.md` - Testing commands and debugging
3. **Verify**: `README.md` - Troubleshooting section

### **For Feature Development**
1. **Plan**: `docs/DEVELOPMENT_NOTES.md` - Architecture patterns
2. **Implement**: `AGENTS.md` - Code style and best practices
3. **Test**: `AGENTS.md` - Testing framework
4. **Document**: Update `docs/DEVELOPMENT_HISTORY.md`

### **For Deployment**
1. **Status**: `IMPLEMENTATION_STATUS.md` - System readiness
2. **Commands**: `AGENTS.md` - Docker deployment
3. **Troubleshooting**: `README.md` - Common issues

---

## **Current Project State (v1.0.6)**

### **✅ Working Features**
- GBP-based trading with 8 trading pairs
- USD market data → GBP display conversion
- AI model signals for all pairs
- Currency switcher (USD ↔ GBP) with persistence
- Real-time market conditions display
- Portfolio valuation in USD/GBP
- Risk management with 1% per trade limit
- Web dashboard with full controls
- Docker containerized deployment
- Memory cgroup limits (1.5GB)

### **✅ Recent Fixes**
- Currency switcher persistence (await keywords added)
- Market conditions data display (invalid GBP-USD call removed)
- API route ordering (specific routes before catch-all)
- UI layout (crypto balance moved under price)

### **🔧 Known Limitations**
- Some pairs use USD→GBP conversion fallback
- AI models trained on USD data
- GBP prices depend on USD→GBP exchange rate
- No automated balance management (manual only)

---

## **Quick Command Reference**

### **Development Commands**
```bash
# Format code
black src/ config/ main.py --line-length=88

# Type check
mypy src/ main.py --ignore=venv/ --no-error-summary

# Lint
flake8 src/ --max-line-length=88 --extend-ignore=E203,W503

# Run tests
python test_ai.py

# Run specific test
python -c "from test_ai import test_technical_indicators; test_technical_indicators()"
```

### **Docker Commands**
```bash
# Build and run
docker compose up --build -d

# View logs
docker logs crypto-trader-bot

# Restart
docker compose restart crypto-trader-bot

# Stop
docker compose down
```

### **API Testing**
```bash
# Check status
curl http://localhost:8000/api/status

# Test currency switch
curl -X POST http://localhost:8000/api/settings/display_currency \
  -H "Content-Type: application/json" -d '{"value": "GBP"}'

# Check API permissions
curl http://localhost:8000/api/check-api-permissions
```

---

## **File Structure Reference**

```
crypto-trader-bot/
├── README.md                    # Main documentation (user & developer)
├── AGENTS.md                   # AI/Assistant guidelines
├── IMPLEMENTATION_STATUS.md      # Project completion status
├── PLAN.md                     # Project planning document
├── docs/
│   ├── DEVELOPMENT_NOTES.md     # Architecture & design docs
│   ├── DEVELOPMENT_HISTORY.md    # Change log & fixes (NEW)
│   ├── pi-boot-recovery-plan.md # Pi recovery procedures
│   └── memory-cgroup-plan.md   # Memory configuration plan
├── config/
│   ├── settings.py              # Trading configuration
│   └── api_keys.env            # API credentials (not committed)
├── src/
│   ├── ai_model.py             # ML trading signals
│   ├── coinbase_api.py         # Coinbase API wrapper
│   ├── currency_utils.py        # Currency conversion
│   ├── data_collector.py        # Market data collection
│   ├── database.py             # SQLite operations
│   ├── risk_manager.py         # Risk management
│   ├── trading_engine.py       # Trading logic
│   └── templates/
│       ├── dashboard.html       # Main dashboard
│       └── settings.html      # Settings page
├── main.py                     # Application entry point
├── test_ai.py                 # AI model tests
└── requirements.txt            # Python dependencies
```

---

## **Documentation Maintenance**

### **When to Update Documentation:**
- ✅ New features implemented
- ✅ Bug fixes applied
- ✅ Architecture changes
- ✅ Configuration changes
- ✅ New API endpoints added
- ✅ Breaking changes introduced

### **How to Update:**
1. **Add to DEVELOPMENT_HISTORY.md** for all changes
2. **Update AGENTS.md** for new patterns or fixes
3. **Update README.md** for user-facing changes
4. **Update DEVELOPMENT_NOTES.md** for architecture changes
5. **Version increment** in README.md header

---

## **Contact & Support**

### **For Questions:**
- Review `AGENTS.md` for code patterns
- Check `docs/DEVELOPMENT_HISTORY.md` for similar issues
- Refer to `README.md` troubleshooting section

### **For Issues:**
- Check Docker logs: `docker logs crypto-trader-bot`
- Verify API permissions: `/api/check-api-permissions`
- Test currency switching: `/api/settings/display_currency`
- Check market data: `/api/status`

---

**Last Updated**: 2026-01-27
**Current Version**: v1.0.6
**Documentation Status**: ✅ Complete & Up-to-Date
