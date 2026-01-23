from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import sys
import os

# Add src to path
sys.path.append('/app/src')
from src.database import db_manager
from src.logger import logger

# Create simple FastAPI app just for testing
app = FastAPI()

@app.post("/api/trades/clear")
async def clear_trades_api(request: Request):
    """Clear all trades from database."""
    try:
        result = db_manager.clear_all_trades()
        return {"success": True, "message": f"Cleared {result} trades from database"}
    except Exception as e:
        logger.error(f"Failed to clear trades: {e}")
        return {"success": False, "error": str(e)}