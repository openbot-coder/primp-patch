"""httpx + aiohttp layers for primp_patch.

httpx: patch Client._send_single_request / AsyncClient._send_single_request —
       route through primp (sync Client / AsyncClient), return real httpx.Response
       objects with ByteStream so the rest of httpx (redirects, cookies, encodings)
       keeps working.

aiohttp: patch ClientSession._request (async) — build a primp AsyncClient request
       and wrap into a duck-typed ClientResponse supporting status/read/text/json/
       headers/release/close/context-manager, enough for the vast majority of users.
"""
from __future__ import annotations

import asyncio
import json as _json
from typing import Any

from .transport import _env_proxy

_originals: dict = {}
_STATE = {"httpx": False, "aiohttp": False}


# ------------------------------------------------------------------- helpers
def _primp_proxy(proxy: str | None) -> str | None:
    import os
    return proxy or os.environ.get("PRIMP_PATCH_PROXY") or _env_proxy()


def _build_headers(headers) -> dict | None:
    if headers is None:
        return None
    out = {}
    if hasattr(headers, "raw"):  # httpx.Headers
        items = [(k.decode(), v.decode()) for k, v in headers.raw]
    elif hasattr(headers, "items"):
        items = list(headers.items())
    else:
        items = list(headers)
    for k, v in items:
        kk = k.decode() if isinstance(k, bytes) else k
        vv = v.decode() if isinstance(v, bytes) else v
        if kk.lower() in ("host", "content-length", "transfer-encoding", "connection"):
            continue  # primp manages framing itself; these cause 'malformed headers'
        if kk.lower() == "user-agent" and vv.startswith("python-"):
            continue  # library UA defeats impersonation; let primp send its own
        out[kk] = vv
    return out or None


def _stringify(params):
    if not params:
        return params
    return {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in params.items()}


# --------------------------------------------------------------------- httpx
def _patch_httpx(proxy: str | None = None, impersonate: str = "chrome") -> bool:
    try:
        import httpx
    except ImportError:
        return False
    if _STATE["httpx"]:
        return True

    _originals["httpx.Client._send_single_request"] = httpx.Client._send_single_request
    _originals["httpx.AsyncClient._send_single_request"] = httpx.AsyncClient._send_single_request

    from httpx import Response as HxResponse
    from httpx._content import ByteStream

    _sync_client = {}

    def _do_sync(self, request):
        import primp
        key = id(self)
        client = _sync_client.get(key)
        if client is None:
            px = _primp_proxy(getattr(self, "_primp_proxy", None))
            import os as _os
            px = px or _os.environ.get("PRIMP_PATCH_PROXY") or _os.environ.get("HTTPS_PROXY") or _os.environ.get("https_proxy")
            if px is None:
                import os as _os
                px = _os.environ.get("PRIMP_PATCH_PROXY") or _os.environ.get("HTTPS_PROXY") or _os.environ.get("https_proxy")
            client = primp.Client(impersonate=impersonate, proxy=px)
            _sync_client[key] = client
        r = client.request(
            method=request.method,
            url=str(request.url),
            params=None,  # already encoded in url
            headers=_build_headers(request.headers),
            content=_read_sync_stream(request.stream),
            timeout=_timeout_of(self),
        )
        return r

    def _timeout_of(client) -> float | None:
        try:
            t = client.timeout
            return None if t is None or t is httpx.USE_CLIENT_DEFAULT else float(t)
        except Exception:
            try:
                return float(client.timeout.connect) if client.timeout.connect else None
            except Exception:
                return None

    def _read_sync_stream(stream) -> bytes | None:
        try:
            chunks = [bytes(c) for c in stream]
            data = b"".join(chunks)
            return data or None
        except Exception:
            return None

    def send_single_request(self, request):
        pr = _do_sync(self, request)
        content = pr.content or b""
        hx = HxResponse(
            status_code=pr.status_code,
            headers=list(pr.headers.items()) if pr.headers else [],
            stream=ByteStream(content),
            request=request,
        )
        return hx

    httpx.Client._send_single_request = send_single_request

    # ---- async ----
    _async_client = {}

    async def send_single_request_async(self, request):
        import primp
        key = id(self)
        client = _async_client.get(key)
        if client is None:
            px = _primp_proxy(getattr(self, "_primp_proxy", None))
            import os as _os
            px = px or _os.environ.get("PRIMP_PATCH_PROXY") or _os.environ.get("HTTPS_PROXY") or _os.environ.get("https_proxy")
            if px is None:
                import os as _os
                px = _os.environ.get("PRIMP_PATCH_PROXY") or _os.environ.get("HTTPS_PROXY") or _os.environ.get("https_proxy")
            client = primp.AsyncClient(impersonate=impersonate, proxy=px)
            _async_client[key] = client
        data = _read_sync_stream(request.stream)
        r = await client.request(
            method=request.method,
            url=str(request.url),
            headers=_build_headers(request.headers),
            content=data,
            timeout=_timeout_of(self),
        )
        content = r.content or b""
        hx = HxResponse(
            status_code=r.status_code,
            headers=list(r.headers.items()) if r.headers else [],
            stream=ByteStream(content),
            request=request,
        )
        return hx

    httpx.AsyncClient._send_single_request = send_single_request_async
    _STATE["httpx"] = True
    return True


def _unpatch_httpx():
    if "httpx.Client._send_single_request" in _originals:
        import httpx
        httpx.Client._send_single_request = _originals["httpx.Client._send_single_request"]
        httpx.AsyncClient._send_single_request = _originals["httpx.AsyncClient._send_single_request"]
        _STATE["httpx"] = False


# ------------------------------------------------------------------- aiohttp
def _patch_aiohttp(proxy: str | None = None, impersonate: str = "chrome") -> bool:
    try:
        import aiohttp
    except ImportError:
        return False
    if _STATE["aiohttp"]:
        return True

    _originals["aiohttp.ClientSession._request"] = aiohttp.ClientSession._request

    class _FakeClientResponse:
        """Duck-typed aiohttp.ClientResponse covering the common surface."""

        def __init__(self, method, url, pr):
            self.method = method
            self.url = url
            self.status = pr.status_code
            self.reason = ""
            self._content = pr.content or b""
            self._headers = dict(pr.headers) if pr.headers else {}
            self.ok = self.status < 400
            self._released = False
            self.version_tuple = (1, 1)
            self.charset = "utf-8"
            self.content_type = self._headers.get("content-type", "").split(";")[0]

        # aiohttp headers object-ish
        @property
        def headers(self):
            return self._headers

        async def read(self):
            self._released = True
            return self._content

        async def text(self, encoding="utf-8", errors="strict"):
            return self._content.decode(encoding or self.charset, errors=errors)

        async def json(self, **kw):
            return _json.loads(self._content)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            self._released = True

        def release(self):
            self._released = True
            return _noop_future()

        def close(self):
            self._released = True

        def raise_for_status(self):
            if self.status >= 400:
                exc = getattr(aiohttp, "ClientResponseError", Exception)
                raise exc(self.status, self.url)
            return self

        @property
        def content(self):
            # minimal stream adapter
            import io
            inner = io.BytesIO(self._content)
            outer = self

            class _Stream:
                async def read(self, n=-1):
                    return inner.read(n if n and n > 0 else -1)

                async def readline(self):
                    return inner.readline()

                def at_eof(self):
                    return inner.tell() >= len(outer._content)

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    line = inner.readline()
                    if not line:
                        raise StopAsyncIteration
                    return line

            return _Stream()

        def get_encoding(self):
            return "utf-8"

    def _noop_future():
        f = asyncio.get_event_loop().create_future()
        f.set_result(None)
        return f

    async def _request(self, method, str_or_url, **kw):
        import primp
        # per-session async client
        client = getattr(self, "_primp_async", None)
        if client is None:
            px = _primp_proxy(kw.get("proxy"))
            import os as _os
            px = px or _os.environ.get("PRIMP_PATCH_PROXY") or _os.environ.get("HTTPS_PROXY") or _os.environ.get("https_proxy")
            client = primp.AsyncClient(impersonate=impersonate, proxy=px)
            self._primp_async = client
        data = kw.get("data")
        if isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        elif data is not None and not isinstance(data, (str, bytes)):
            data = str(data).encode()
        params = kw.get("params")
        headers = _build_headers(kw.get("headers"))
        timeout = kw.get("timeout")
        to = None
        if timeout is not None and not isinstance(timeout, object.__class__ or type):
            to = getattr(timeout, "total", None)
            if to is not None:
                try:
                    to = float(to)
                except Exception:
                    to = None
        r = await client.request(
            method=method,
            url=str(str_or_url),
            params=_stringify(params),
            headers=headers,
            data=data,
            json=kw.get("json"),
            timeout=to,
        )
        return _FakeClientResponse(method, str(str_or_url), r)

    aiohttp.ClientSession._request = _request
    _STATE["aiohttp"] = True
    return True


def _unpatch_aiohttp():
    if "aiohttp.ClientSession._request" in _originals:
        import aiohttp
        aiohttp.ClientSession._request = _originals["aiohttp.ClientSession._request"]
        _STATE["aiohttp"] = False
