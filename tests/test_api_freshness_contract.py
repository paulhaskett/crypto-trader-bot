"""Tests for the API freshness metadata contract."""

from src.api_contract import attach_meta, response_meta


def test_fresh_response_has_source_timestamp_and_request_id():
    result = attach_meta({"status": "success", "value": 12}, data_status="fresh", source="coinbase")

    assert result["data_status"] == "fresh"
    assert result["source"] == "coinbase"
    assert result["error_code"] is None
    assert result["as_of"]
    assert len(result["request_id"]) == 32
    assert result["value"] == 12


def test_unavailable_response_has_explicit_error_code():
    result = response_meta(
        "unavailable",
        "coinbase",
        as_of="2026-09-28T15:00:00+00:00",
        error_code="account_fetch_failed",
    )

    assert result == {
        "data_status": "unavailable",
        "as_of": "2026-09-28T15:00:00+00:00",
        "source": "coinbase",
        "error_code": "account_fetch_failed",
        "request_id": result["request_id"],
    }


def test_metadata_does_not_mutate_original_payload():
    original = {"status": "success"}
    result = attach_meta(original, data_status="fresh", source="database")

    assert original == {"status": "success"}
    assert result is not original
