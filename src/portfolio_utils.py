"""Pure portfolio valuation helpers used by the dashboard API."""


def account_value_gbp(currency: str, balance: float, usd_gbp_rate: float, eur_gbp_rate: float) -> float:
    """Convert an account balance to GBP without treating USD as GBP."""
    amount = float(balance or 0.0)
    if currency == "GBP":
        return amount
    if currency in {"USD", "USDC"}:
        return amount * float(usd_gbp_rate)
    if currency == "EUR":
        return amount * float(eur_gbp_rate)
    raise ValueError(f"Unsupported fiat currency: {currency}")
