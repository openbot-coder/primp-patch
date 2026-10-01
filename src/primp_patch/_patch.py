"""Runtime HTTP-layer replacement: route requests/urllib3/http.client/urllib through primp."""
from __future__ import annotations

import http.client as _hc
import urllib.request as _ur

from .transport import Response, Session, transport_request, _env_proxy
from ._async_layers import (
    _patch_httpx, _unpatch_httpx, _patch_aiohttp, _unpatch_aiohttp,
)

__all__ = ["patch", "unpatch", "is_patched"]

_STATE = {
    "requests": False,
    "urllib3": False,
    "http.client": False,
    "urllib": False,
    "httpx": False,
    "aiohttp": False,
}

_originals: dict = {}


# ------------------------------------------------------------------ requests
def _patch_requests(session_cls=None):
    try:
        import requests
    except ImportError:
        return False
    if _STATE["requests"]:
        return True

    _originals["requests.Session.request"] = requests.Session.request

    def request(self, method, url, params=None, data=None, headers=None,
                cookies=None, files=None, auth=None, timeout=None,
                allow_redirects=True, proxies=None, hooks=None, stream=None,
                verify=None, cert=None, json=None, **kw):
        if proxies is None and getattr(self, "proxies", None):
            proxies = self.proxies
        _apply_proxies(proxies)
        resp = transport_request(method, url, params=params, data=data, json=json,
                                 headers=headers, timeout=timeout)
        return _to_requests_response(resp, requests)

    requests.Session.request = request
    _STATE["requests"] = True
    return True


def _to_requests_response(resp: Response, requests_mod):
    r = requests_mod.Response()
    r.status_code = resp.status_code
    r._content = resp.content
    r.headers = dict(resp.headers) if resp.headers else {}
    r.url = resp.url
    r.encoding = "utf-8"
    # minimal ok/history flags
    try:
        r.reason = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                    404: "Not Found", 429: "Too Many Requests",
                    500: "Internal Server Error"}.get(resp.status_code, "")
    except Exception:
        pass
    return r


def _unpatch_requests():
    try:
        import requests
        import yfinance_patch_store  # noqa: placeholder
    except ImportError:
        pass
    if "requests.Session.request" in _originals:
        import requests
        requests.Session.request = _originals["requests.Session.request"]
        _STATE["requests"] = False


def _apply_proxies(proxies):
    """Set env-level proxy from a requests-style proxies dict."""
    import os
    if isinstance(proxies, dict) and proxies:
        p = proxies.get("https") or proxies.get("http")
        if p and not os.environ.get("PRIMP_PATCH_PROXY_LOCKED"):
            os.environ["PRIMP_PATCH_PROXY"] = p


# ------------------------------------------------------------------- urllib3
def _patch_urllib3():
    try:
        import urllib3
    except ImportError:
        return False
    if _STATE["urllib3"]:
        return True

    _originals["urllib3.PoolManager.urlopen"] = urllib3.PoolManager.urlopen

    def urlopen(self, method, url, body=None, headers=None, retries=None,
                redirect=True, assert_same_host=True, timeout=None,
                pool_timeout=None, release_conn=None, chunked=False,
                body_pos=None, **kw):
        import json as _json
        # urllib3 passes body as bytes/str
        json_payload = None
        data_payload = body
        ct = (headers or {}).get("Content-Type", "") if isinstance(headers, dict) else ""
        if ct and "json" in ct and body:
            try:
                json_payload = _json.loads(body) if isinstance(body, (str, bytes)) else body
                data_payload = None
            except Exception:
                pass
        _apply_proxies(getattr(self, "proxies", None) or kw.get("proxies"))
        resp = transport_request(method, url, params=None, data=data_payload,
                                 json=json_payload, headers=headers, timeout=timeout)
        return _to_urllib3_response(resp, urllib3)

    urllib3.PoolManager.urlopen = urlopen
    _STATE["urllib3"] = True
    return True


def _to_urllib3_response(resp: Response, urllib3_mod):
    r = urllib3_mod.HTTPResponse(
        body=resp.content,
        headers=dict(resp.headers) if resp.headers else {},
        status=resp.status_code,
        request_url=resp.url,
    )
    return r


def _unpatch_urllib3():
    if "urllib3.PoolManager.urlopen" in _originals:
        import urllib3
        urllib3.PoolManager.urlopen = _originals["urllib3.PoolManager.urlopen"]
        _STATE["urllib3"] = False


# --------------------------------------------------------------- http.client
def _patch_http_client():
    if _STATE["http.client"]:
        return True
    _originals["HTTPConnection.request"] = _hc.HTTPConnection.request
    _originals["HTTPSConnection.request"] = _hc.HTTPSConnection.request

    def request(self, method, url, body=None, headers=None, *, encode_chunked=False):
        import json as _json
        json_payload = None
        data_payload = body
        if isinstance(body, (dict, list)):
            json_payload = body
            data_payload = None
        elif isinstance(body, (str, bytes)):
            ct = (headers or {}).get("Content-Type", "") if isinstance(headers, dict) else ""
            if "json" in ct:
                try:
                    json_payload = _json.loads(body)
                    data_payload = None
                except Exception:
                    pass
        host_header = (headers or {}).get("Host") if isinstance(headers, dict) else None
        scheme = "https" if isinstance(self, _hc.HTTPSConnection) else "http"
        full = f"{scheme}://{self.host}" + (f":{self.port}" if self.port not in (80, 443) else "") + url
        resp = transport_request(method, full, data=data_payload, json=json_payload,
                                 headers=headers, timeout=self.timeout or None)
        # Stuff the translated response back into a real HTTPResponse-shaped object
        self._primp_last = resp
        # Build a lightweight response object with the http.client API surface
        return self._primp_last and _build_httpresponse(resp, self, method)

    _originals["HTTPConnection.getresponse"] = _hc.HTTPConnection.getresponse

    def getresponse(self):
        resp = getattr(self, "_primp_last", None)
        if resp is not None:
            self._primp_last = None
            return _build_httpresponse(resp, self, "GET")
        return _originals["HTTPConnection.getresponse"](self)

    _hc.HTTPConnection.request = request
    _hc.HTTPSConnection.request = request
    _hc.HTTPConnection.getresponse = getresponse
    _hc.HTTPSConnection.getresponse = getresponse
    _STATE["http.client"] = True
    return True


class _FakeHTTPResponse:
    """Duck-typed http.client response (HTTPResponse requires a real socket fp)."""
    def __init__(self, resp: Response):
        self.status = resp.status_code
        self.reason = ""
        self._content = resp.content or b""
        self._headers = resp.headers
        self.url = resp.url
        self.version = 11
        self.will_close = True
        self.length = len(self._content)
    def read(self, amt=None, **kw):
        d, self._content = self._content, b""
        self.length = 0
        return d
    def readinto(self, b):
        n = min(len(b), len(self._content))
        b[:n] = self._content[:n]
        self._content = self._content[n:]
        return n
    def readline(self, *a):
        raise NotImplementedError
    def getheader(self, name, default=None):
        if not self._headers: return default
        try:
            return self._headers.get(name, default)
        except Exception:
            return default
    def getheaders(self):
        return list(self._headers.items()) if self._headers else []
    @property
    def headers(self):
        return self._headers
    @property
    def code(self):
        return self.status
    def isclosed(self):
        return True
    def close(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass


def _build_httpresponse(resp: Response, conn, method):
    return _FakeHTTPResponse(resp)


def _unpatch_http_client():
    if "HTTPConnection.request" in _originals:
        _hc.HTTPConnection.request = _originals["HTTPConnection.request"]
        _hc.HTTPSConnection.request = _originals["HTTPSConnection.request"]
        _hc.HTTPConnection.getresponse = _originals["HTTPConnection.getresponse"]
        _hc.HTTPSConnection.getresponse = _originals["HTTPConnection.getresponse"]
        _STATE["http.client"] = False


# -------------------------------------------------------------------- urllib
def _patch_urllib():
    if _STATE["urllib"]:
        return True
    _originals["urllib.request.urlopen"] = _ur.urlopen

    def urlopen(url, data=None, timeout=None, *, context=None, **kw):
        import json as _json
        if isinstance(url, _ur.Request):
            method = url.get_method()
            full_url = url.full_url
            payload = url.data
            headers = dict(url.header_items())
        else:
            method = "POST" if data else "GET"
            full_url = url
            payload = data
            headers = None
        json_payload = None
        data_payload = payload
        ct = (headers or {}).get("Content-type", "") if isinstance(headers, dict) else ""
        if ct and "json" in ct and payload:
            try:
                json_payload = _json.loads(payload) if isinstance(payload, (str, bytes)) else payload
                data_payload = None
            except Exception:
                pass
        resp = transport_request(method, full_url, data=data_payload,
                                 json=json_payload, headers=headers, timeout=timeout)
        return _build_urlibresponse(resp)

    _ur.urlopen = urlopen
    _STATE["urllib"] = True
    return True


def _build_urlibresponse(resp: Response):
    import io as _io
    # addinfourl.status is a read-only property in 3.9+; code kwarg already sets it
    r = _ur.addinfourl(_io.BytesIO(resp.content or b""),
                       dict(resp.headers) if resp.headers else {},
                       resp.url or "", code=resp.status_code)
    return r


def _unpatch_urllib():
    if "urllib.request.urlopen" in _originals:
        _ur.urlopen = _originals["urllib.request.urlopen"]
        _STATE["urllib"] = False


# -------------------------------------------------------------------- public
def patch(requests_: bool = True, urllib3_: bool = True,
          http_client: bool = True, urllib_: bool = True,
          httpx_: bool = True, aiohttp_: bool = True,
          proxy: str | None = None,
          impersonate: str = "chrome") -> dict:
    """Replace low-level HTTP backends with primp.

    Args:
        requests_: patch requests.Session.request
        urllib3_: patch urllib3.PoolManager.urlopen
        http_client: patch http.client.HTTP(S)Connection.request
        urllib_: patch urllib.request.urlopen
        proxy: default proxy (falls back to PRIMP_PATCH_PROXY / HTTPS_PROXY / HTTP_PROXY)

    Returns dict of {layer: bool} for what actually got patched.
    """
    if proxy:
        import os
        os.environ["PRIMP_PATCH_PROXY"] = proxy
        os.environ["PRIMP_PATCH_PROXY_LOCKED"] = "1"
    result = {}
    if requests_:
        result["requests"] = _patch_requests()
    if urllib3_:
        result["urllib3"] = _patch_urllib3()
    if http_client:
        result["http.client"] = _patch_http_client()
    if urllib_:
        result["urllib"] = _patch_urllib()
    if httpx_:
        result["httpx"] = _patch_httpx(proxy=proxy, impersonate=impersonate)
    if aiohttp_:
        result["aiohttp"] = _patch_aiohttp(proxy=proxy, impersonate=impersonate)
    return result


def unpatch():
    _unpatch_httpx()
    _unpatch_aiohttp()
    _unpatch_requests()
    _unpatch_urllib3()
    _unpatch_http_client()
    _unpatch_urllib()


def is_patched() -> dict:
    return dict(_STATE)
