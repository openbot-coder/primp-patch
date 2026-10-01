"""Core transport: translate requests/urllib-style calls to primp."""

from __future__ import annotations

import json as _json
import threading
from typing import Any

import primp

_sentinel = object()
DEFAULT_IMPERSONATE = "chrome"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class TransportError(Exception):
    pass


class HTTPError(Exception):
    def __init__(self, response):
        self.response = response
        super().__init__(f"{response.status_code} error for {getattr(response, 'url', '?')}")


class Response:
    """Backend-agnostic response facade (requests-like)."""

    def __init__(self, r: Any = None):
        self._r = r
        if r is not None:
            self.status_code = r.status_code
            self.text = r.text
            self.content = r.content
            self.headers = r.headers
            self.url = str(r.url) if getattr(r, "url", None) is not None else None

    def json(self, **kw):
        return self._r.json(**kw)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(self)
        return self

    @property
    def ok(self):
        return self.status_code < 400

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Jar:
    """CookieJar-ish: update()/clear()/._cookies + .jar self-reference."""

    def __init__(self):
        self._cookies: dict = {}

    def update(self, d):
        self._cookies.update(d or {})

    def clear(self):
        self._cookies.clear()

    def get_dict(self):
        return dict(self._cookies)

    @property
    def jar(self):
        return self

    def __iter__(self):
        return iter(self._cookies.items())

    def __contains__(self, k):
        return k in self._cookies

    def __getitem__(self, k):
        return self._cookies[k]


class Cookies(Jar):
    pass


class Session:
    """requests.Session-like facade over one primp.Client."""

    def __init__(self, impersonate: str = DEFAULT_IMPERSONATE, proxy: str | None = _sentinel, **kw):
        self.impersonate = impersonate
        if proxy is _sentinel:
            proxy = _env_proxy()
        self._proxy = proxy
        self._lock = threading.Lock()
        self._client = self._new_client()
        self.cookies = Cookies()
        self.headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
        }
        self.verify = True
        self.trust_env = True

    def _new_client(self):
        return primp.Client(impersonate=self.impersonate, proxy=self._proxy)

    # ---- proxies like requests: dict or str -----------------------------
    @property
    def proxies(self):
        return self._proxies

    @proxies.setter
    def proxies(self, value):
        self._proxies = value
        if value:
            p = (value.get("https") or value.get("http")) if isinstance(value, dict) else value
            if p and p != self._proxy:
                self._proxy = p
                self._client = self._new_client()

    @staticmethod
    def _stringify(params):
        if not params:
            return params
        return {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in params.items()}

    @staticmethod
    def _clean_kw(kw: dict) -> dict:
        for k in ("allow_redirects", "verify", "cert", "stream", "proxies",
                  "auth", "files", "cookies"):
            kw.pop(k, None)
        return kw

    def _merged(self, headers):
        h = dict(self.headers)
        if headers:
            h.update(headers)
        return h or None

    def request(self, method: str, url: str, params=None, data=None, json=None,
                headers=None, timeout=None, **kw) -> Response:
        kw = self._clean_kw(kw)
        m = method.upper()
        fn = getattr(self._client, m.lower(), None)
        if fn is None:
            raise TransportError(f"primp has no method {m}")
        r = fn(url=url, params=self._stringify(params), json=json, data=data,
               headers=self._merged(headers), timeout=timeout, **kw)
        return Response(r)

    def get(self, url, params=None, **kw):
        return self.request("GET", url, params=params, **kw)

    def post(self, url, data=None, json=None, **kw):
        return self.request("POST", url, data=data, json=json, **kw)

    def put(self, url, data=None, **kw):
        return self.request("PUT", url, data=data, **kw)

    def patch(self, url, data=None, **kw):
        return self.request("PATCH", url, data=data, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    def head(self, url, **kw):
        return self.request("HEAD", url, **kw)

    def options(self, url, **kw):
        return self.request("OPTIONS", url, **kw)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def transport_request(method: str, url: str, **kw) -> Response:
    """One-shot request using a shared client (for urllib-style entry points)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Session(proxy=_env_proxy())
    return _shared.request(method, url, **kw)


def _env_proxy() -> str | None:
    import os
    return (
        os.environ.get("PRIMP_PATCH_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
    )


_shared: Session | None = None
_shared_lock = threading.Lock()


def reset_shared():
    global _shared
    with _shared_lock:
        _shared = None
