"""Tests for API security headers and mutation authentication/CSRF."""

import asyncio

from starlette.requests import Request
from starlette.responses import Response

from src.api_worker import security_and_audit_middleware


def make_request(method, path, request_id=None, token=None, csrf=None):
    headers = []
    if request_id:
        headers.append((b'x-request-id', request_id.encode()))
    if token:
        headers.append((b'authorization', f'Bearer {token}'.encode()))
    if csrf:
        headers.append((b'x-dashboard-csrf', csrf.encode()))
    return Request({
        'type': 'http', 'method': method, 'path': path, 'headers': headers,
        'query_string': b'', 'scheme': 'http', 'server': ('localhost', 8000),
        'client': ('127.0.0.1', 1234),
    })


def ok_call_next(_request):
    async def call_next(_inner_request):
        return Response('ok')
    return call_next


def test_security_headers_and_request_id_are_present():
    response = asyncio.run(security_and_audit_middleware(make_request('GET', '/api/health'), ok_call_next(None)))
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'same-origin'
    assert response.headers['X-Request-ID']
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert response.headers['Cache-Control'] == 'no-store'


def test_mutations_fail_closed_when_auth_is_not_configured(monkeypatch):
    monkeypatch.delenv('DASHBOARD_AUTH_TOKEN', raising=False)
    response = asyncio.run(security_and_audit_middleware(make_request('POST', '/api/control/retrain'), ok_call_next(None)))
    assert response.status_code == 503
    assert b'auth_not_configured' in response.body


def test_valid_token_requires_matching_csrf_header(monkeypatch):
    monkeypatch.setenv('DASHBOARD_AUTH_TOKEN', 'test-token')
    denied = asyncio.run(security_and_audit_middleware(make_request('POST', '/api/control/retrain', token='test-token'), ok_call_next(None)))
    allowed = asyncio.run(security_and_audit_middleware(make_request('POST', '/api/control/retrain', token='test-token', csrf='test-token'), ok_call_next(None)))
    assert denied.status_code == 403
    assert allowed.status_code == 200
