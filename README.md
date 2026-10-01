# primp-patch

One line to route **all** of your Python HTTP traffic through [primp](https://github.com/deedy5/primp) — the rnet-based client with real browser TLS/JA3/JA4 fingerprinting.

```python
import primp_patch
primp_patch.patch()

import requests  # unchanged code, primp transport
requests.get("https://example.com")
```

## Why

Libraries and SDKs hard-code `requests`, `urllib3`, `http.client` or `urllib`. Swapping the HTTP
backend means forking each one. `primp-patch` instead replaces the transport *at runtime*, so
existing code — including third-party packages — inherits browser-grade impersonation with zero
source changes.

## What gets patched

| Layer | Entry point | Covers |
|---|---|---|
| `requests` | `requests.Session.request` | every `requests.get/post/...` |
| `urllib3` | `urllib3.PoolManager.urlopen` | anything built on urllib3 pools |
| `http.client` | `HTTPConnection.request` / `HTTPSConnection.request` | stdlib HTTPConnection users |
| `urllib` | `urllib.request.urlopen` | `urllib.request` users |
| `httpx` | `Client._send_single_request` (+ async) | httpx sync & async, openai/anthropic SDKs |
| `aiohttp` | `ClientSession._request` | async clients & scrapers |

## Install

```bash
pip install primp-patch
# with extras
pip install "primp-patch[all]"
```

## Usage

```python
import primp_patch
primp_patch.patch(proxy="http://host:port")     # explicit proxy

# or via environment
#   PRIMP_PATCH_PROXY=http://host:port
#   or HTTPS_PROXY / HTTP_PROXY

# selective patching
primp_patch.patch(urllib3_=False)

# inspect / revert
primp_patch.is_patched()
primp_patch.unpatch()
```

### Auto-patch on import

```bash
export PRIMP_PATCH_AUTO=1
python -c "import primp_patch, requests; print(requests.get('https://example.com').status_code)"
```

## Notes & limitations

- `stream=True`, `files=`, `auth=`, custom `verify`/`cert` are not translated (primp has no
  equivalent); they are silently dropped rather than raising.
- Cookie jars are tracked in-process but not persisted.
- Redirect handling is delegated to primp; `allow_redirects=False` is not honored.
- Intended for clients that need anti-bot robustness, not as a drop-in for every edge case.

## License

MIT
