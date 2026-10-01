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

## pcurl — curl 平替（内置 CLI）

v0.2.0 起内置 `pcurl`：primp 内核的 curl 风格命令行，默认 Chrome TLS/JA3 指纹。

```bash
pip install primp-patch          # 安装后自带 pcurl 命令
python -m primp_patch.curl ...   # 或不经 PATH 直接调用

pcurl https://api.github.com/zen                 # GET，Chrome 指纹
pcurl -s https://httpbin.org/get                 # -s 静默（状态行不打 stderr）
pcurl -si https://example.com                    # -i 含响应头
pcurl -X POST https://httpbin.org/post -d 'a=1&b=2'
pcurl -j https://httpbin.org/post <<< '{"k":"v"}'  # JSON 快捷（stdin）
pcurl -o page.html https://example.com           # 落盘
pcurl -L -k --max-time 10 --proxy http://127.0.0.1:7890 https://target
pcurl --impersonate firefox https://example.com  # 换指纹档位
pcurl --no-fingerprint https://example.com       # 不做 TLS 伪装
```

- 代理默认取 `$PRIMP_PATCH_PROXY` / `$HTTPS_PROXY`
- 档位（primp 2.x）：`chrome_146`（默认）、`chrome_145`、`firefox`、`safari`、`edge`
- 退出码对齐 curl：6 解析失败 / 7 连接失败 / 22 `--fail` 时 4xx/5xx / 28 超时
