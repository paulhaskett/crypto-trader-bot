Implement the following decisions:

1. Prioritize a small set of high-liquidity pairs (BTC/USD, ETH/USD).
   Use WebSocket feeds for real-time data and minimize REST calls to stay within rate limits.

2. Use aggregated multi-exchange OHLC data for historical analysis and backtesting.
   Use real-time aggregated prices for live trading and execution.

3. Use consensus averaging (volume-weighted) with outlier filtering (1–2% deviation from median).
   Track spread across exchanges and reduce or pause trading if divergence exceeds 2–3%.

4. Use Chainlink only as a verification layer.
   If aggregated price deviates significantly from Chainlink, flag anomaly but do not trade on Chainlink data.

5. Implement failover so the system continues operating if any single data source fails.

Goal: create a stable, multi-source, manipulation-resistant price feed suitable for live trading.
