# Use Python 3.13 slim image for Raspberry Pi (ARM64)
FROM python:3.13-slim

# NOTE on timezone: Container intentionally runs in UTC.
# Bot logs use UTC timestamps (matches Coinbase, Binance, all exchange APIs).
# The /tmp/trail_capture_watcher.py displays times in BST for the operator.
# DO NOT change container to Europe/London — would create mixed UTC/BST in
# /app/logs/trading.log during DST transitions, and break cross-platform
# log analysis. If you want local-time display, convert at the display
# layer (watcher, dashboard), not at the container level.

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# Expose port for dashboard
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/health')" || exit 1

# Default command runs the startup script (trading + API workers)
CMD ["python", "src/startup.py"]