"""Tests for API security headers and mutation audit metadata."""

import asyncio

from starlette.requests import Request
from starlette.responses import Response

from src.api_worker import security_and_audit_middleware


def make_request(method, path, request_id=None):
    headers = []
    if request_id:
        headers.append((b'x-request-id', request_id.encode()))
    return Request({
        'type': 'http',
        'method': method,
        'path': path,
        'headers': headers,
        'query_string': b'',
        'scheme': 'http',
        'server': ('localhost', 8000),
        'client': ('127.0.0.1', 1234),
    })


def test_security_headers_and_request_id_are_present():
    async def call_next(request):
        return Response('ok')

    response = asyncio.run(security_and_audit_middleware(make_request('GET', '/api/health'), call_next))

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'same-origin'
    assert response.headers['X-Request-ID']
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert response.headers['Cache-Control'] == 'no-store'


def test_supplied_request_id_is_preserved_on_mutation_response():
    async def call_next(request):
        return Response('ok')

    response = asyncio.run(security_and_audit_middleware(
        make_request('POST', '/api/control/retrain', 'test-request-id'),
        call_next,
    ))

    assert response.headers['X-Request-ID'] == 'test-request-id'
