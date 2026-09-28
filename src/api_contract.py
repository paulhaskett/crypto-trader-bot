"""Shared metadata for truthful API freshness and availability states.

The dashboard must distinguish fresh data, stale cached data, unavailable data,
and genuinely empty data. These helpers centralize the response fields without
changing the domain payloads used by existing pages.
"""

from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, Dict, Optional


def response_meta(
    data_status: str,
    source: str,
    *,
    as_of: Optional[str] = None,
    error_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Return standard freshness metadata for an API response."""
    return {
        "data_status": data_status,
        "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        "source": source,
        "error_code": error_code,
        "request_id": uuid4().hex,
    }


def attach_meta(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Attach standard freshness metadata without replacing payload fields."""
    result = dict(payload)
    result.update(response_meta(**kwargs))
    return result
