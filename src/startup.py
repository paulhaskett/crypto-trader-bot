#!/usr/bin/env python3
"""
Startup script for crypto trading bot.
Launches both the trading process and API workers.
"""
import os
import sys
import time
import signal
import subprocess
from pathlib import Path

# Import from centralized cache_manager
from src.cache_manager import BASE_DIR

os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

NUM_WORKERS = int(os.getenv('NUM_WORKERS', '2'))
API_READY_TIMEOUT = 30


class BotStarter:
    def __init__(self):
        self.trading_process = None
        self.gunicorn_process = None
        
    def start_trading(self):
        """Start the trading loop in a subprocess."""
        print("=" * 60, flush=True)
        print("STARTING TRADING PROCESS", flush=True)
        print("=" * 60, flush=True)
        
        self.trading_process = subprocess.Popen(
            [sys.executable, 'src/trading_loop.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True
        )
        print(f"Trading process started (PID: {self.trading_process.pid})", flush=True)
        
        def read_output():
            try:
                for line in self.trading_process.stdout:
                    print(f"[TRADING] {line}", end='', flush=True)
            except:
                pass
        
        import threading
        threading.Thread(target=read_output, daemon=True).start()
    
    def start_api_workers(self):
        """Start gunicorn with multiple workers."""
        print("=" * 60, flush=True)
        print(f"STARTING API WORKERS ({NUM_WORKERS} workers)", flush=True)
        print("=" * 60, flush=True)
        
        gunicorn_cmd = [
            'gunicorn',
            'src.api_worker:app',
            '--workers', str(NUM_WORKERS),
            '--bind', '0.0.0.0:8000',
            '--access-logfile', '-',
            '--error-logfile', '-',
            '--worker-class', 'uvicorn.workers.UvicornWorker',
            '--timeout', '1800',
            '--keep-alive', '5'
        ]
        
        self.gunicorn_process = subprocess.Popen(
            gunicorn_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True
        )
        print(f"API workers started (PID: {self.gunicorn_process.pid})", flush=True)
        
        def read_output():
            try:
                for line in self.gunicorn_process.stdout:
                    print(f"[API] {line}", end='', flush=True)
            except:
                pass
        
        import threading
        threading.Thread(target=read_output, daemon=True).start()
    
    def wait_for_api_ready(self, timeout=API_READY_TIMEOUT):
        """Wait for API to be ready."""
        import urllib.request
        start = time.time()
        print(f"Waiting for API workers to be ready (timeout: {timeout}s)...", flush=True)
        
        while time.time() - start < timeout:
            try:
                urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)
                elapsed = time.time() - start
                print(f"API workers ready! (took {elapsed:.1f}s)", flush=True)
                return True
            except Exception as e:
                time.sleep(1)
        
        print("WARNING: API may not be ready", flush=True)
        return False
    
    def check_process_health(self):
        """Check if processes are still healthy."""
        if self.trading_process and self.trading_process.poll() is not None:
            return False, "Trading process died"
        if self.gunicorn_process and self.gunicorn_process.poll() is not None:
            return False, "Gunicorn died"
        return True, "OK"
    
    def run(self):
        """Start both components and wait."""
        self.start_trading()
        
        time.sleep(3)
        
        self.start_api_workers()
        
        self.wait_for_api_ready()
        
        print("\n" + "=" * 60, flush=True)
        print("CRYPTO TRADING BOT STARTED", flush=True)
        print("=" * 60, flush=True)
        print(f"  Trading: Running in background process", flush=True)
        print(f"  API: {NUM_WORKERS} workers on port 8000", flush=True)
        print(f"  Dashboard: http://localhost:8000", flush=True)
        print("=" * 60 + "\n", flush=True)
        
        def signal_handler(sig, frame):
            print("\nShutdown signal received...", flush=True)
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            while True:
                healthy, status = self.check_process_health()
                if not healthy:
                    print(f"Process health check failed: {status}", flush=True)
                    break
                time.sleep(10)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Stop all processes."""
        print("Stopping processes...", flush=True)
        
        if self.trading_process:
            self.trading_process.terminate()
            try:
                self.trading_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.trading_process.kill()
                self.trading_process.wait()
        
        if self.gunicorn_process:
            self.gunicorn_process.terminate()
            try:
                self.gunicorn_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.gunicorn_process.kill()
                self.gunicorn_process.wait()
        
        print("All processes stopped", flush=True)


if __name__ == "__main__":
    BotStarter().run()
