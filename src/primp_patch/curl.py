#!/usr/bin/env python3
"""pcurl — curl 风格命令行，primp 内核（浏览器 TLS/JA3 指纹）

用法:
  pcurl [选项] <URL>

描述:
  pcurl 是 curl 的常用子集平替，底层用 primp（rnet 内核）发送请求，
  默认模拟 Chrome 的 TLS/JA3 指纹与 User-Agent，用于访问有反爬
  （TLS 指纹检测）的站点。常规管道用法与 curl 一致：
  响应体写 stdout，状态信息写 stderr，因此 `pcurl url | jq` 无需 -s。

常用示例:
  pcurl https://api.github.com/zen                     # GET（Chrome 指纹）
  pcurl -s https://httpbin.org/get                     # -s 静默（不打印状态行）
  pcurl -si https://example.com                        # -i 输出含响应头
  pcurl -o page.html https://example.com               # 响应体落盘
  pcurl -L https://example.com/redirect                # 跟随重定向（最多 10 跳）
  pcurl -X POST https://httpbin.org/post -d 'a=1&b=2'  # 表单（自动带 urlencoded CT）
  pcurl -d 'a=1' -d 'b=2' URL                          # 多个 -d 用 & 拼接
  pcurl -H 'Authorization: Bearer xxx' URL             # 自定义请求头（可重复）
  echo '{"k":"v"}' | pcurl -j https://httpbin.org/post # JSON 快捷（读 stdin）
  pcurl -j -d '{"k":"v"}' URL                          # JSON 快捷（直接给数据）
  pcurl -F 'file=@photo.jpg' -F 'caption=hi' URL       # multipart 上传
  pcurl -I https://example.com                         # HEAD 请求
  pcurl -k https://self-signed.badssl.com/             # 忽略证书错误
  pcurl --max-time 10 --proxy http://127.0.0.1:7890 URL
  pcurl --impersonate firefox URL                      # 换指纹档位
  pcurl --no-fingerprint URL                           # 关闭 TLS 伪装（普通客户端）
  pcurl -f https://httpbin.org/status/404              # 4xx/5xx 时 exit 22，不输出 body

选项 (curl 兼容子集):
  请求:
  -X, --method <M>       HTTP 方法（默认 GET；有 -d/-F 时自动 POST）
  -d, --data <data>      请求体；可重复，多个值用 & 拼接；自动附加
                         Content-Type: application/x-www-form-urlencoded
                         （除非显式用 -H 指定过 Content-Type）
      --data-raw <data>  同 -d（不支持 @file 语法）
  -H, --header <h>       请求头 "Name: value"（可重复）
  -F, --form <f>         multipart 字段 "k=v" 或 "k=@file"（可重复）
  -j, --json             JSON 快捷：自动加 Content-Type: application/json，
                         数据来自 -d 或 stdin；合法 JSON 时结构化发送
  -I, --head             发 HEAD 请求
  -e  (无)               不支持，请用 -H 'Referer: ...'

  响应控制:
  -o, --output <file>    响应体写入文件（- 表示 stdout，默认）
  -i, --include          输出中包含响应头（HTTP/1.1 200 风格）
  -s, --silent           不向 stderr 打印状态行
  -f, --fail             状态码 >= 400 时不输出 body 且 exit 22
  -L, --location         跟随 3xx 重定向（最多 10 跳）
      --compressed       兼容 curl 而已——primp 始终自动处理压缩

  连接与安全:
  -k, --insecure         跳过 TLS 证书校验
      --proxy <url>      本请求使用的代理；默认取环境变量
                         $PRIMP_PATCH_PROXY，其次 $HTTPS_PROXY
  -m, --max-time <sec>   总超时秒数（默认 30）
      --impersonate <p>  TLS 指纹档位。primp 2.x 可用:
                         chrome_146（默认）/ chrome_145 / firefox /
                         safari / edge；也可用环境变量 $PCURL_IMPERSONATE
      --no-fingerprint   不做 TLS 伪装（使用客户端原生指纹）

  其他:
  -v, --verbose          在 stderr 打印请求摘要
  -h, --help             本帮助

环境变量:
  PRIMP_PATCH_PROXY   默认代理（如 http://127.0.0.1:7890）
  HTTPS_PROXY         次选默认代理
  PCURL_IMPERSONATE   默认指纹档位（--impersonate 可覆盖）

退出码（对齐 curl）:
  0    成功（含 4xx/5xx，除非 --fail）
  2    用法错误（未知选项、缺 URL 等）
  6    域名解析失败
  7    连接失败
  22   --fail 时收到 4xx/5xx
  28   超时

与 curl 的差异:
  * 只支持单个 URL
  * 不支持 -w/--write-out、--resolve、-u（Basic 认证请用 -H
    'Authorization: Basic ...'）、cookie 文件（-b/-c）、@file 请求体
  * 遇到不认识的选项会明确报错（退出码 2），不会静默转发给真 curl
  * -d 自动附加 form-urlencoded 头（与 curl 一致），但 JSON 场景请用 -j
"""
import sys, os, json as _json

def die(msg, code=2):
    print(f"pcurl: {msg}", file=sys.stderr)
    sys.exit(code)

def parse_args(argv):
    o = dict(method=None, data=[], headers=[], forms=[], output=None,
             follow=False, insecure=False, silent=False, include=False,
             head=False, json_mode=False, impersonate=None, proxy=None,
             max_time=None, verbose=False, fail=False, urls=[],
             no_fingerprint=False)
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('-X', '--method'): o['method'] = argv[i+1]; i += 2
        elif a in ('-d', '--data', '--data-raw', '--data-binary'): o['data'].append(argv[i+1]); i += 2
        elif a in ('-H', '--header'): o['headers'].append(argv[i+1]); i += 2
        elif a in ('-F', '--form'): o['forms'].append(argv[i+1]); i += 2
        elif a in ('-o', '--output'): o['output'] = argv[i+1]; i += 2
        elif a in ('-L', '--location'): o['follow'] = True; i += 1
        elif a in ('-k', '--insecure'): o['insecure'] = True; i += 1
        elif a in ('-s', '--silent'): o['silent'] = True; i += 1
        elif a in ('-i', '--include'): o['include'] = True; i += 1
        elif a in ('-I', '--head'): o['head'] = True; i += 1
        elif a in ('-j', '--json'): o['json_mode'] = True; i += 1
        elif a == '--impersonate': o['impersonate'] = argv[i+1]; i += 2
        elif a == '--proxy': o['proxy'] = argv[i+1]; i += 2
        elif a in ('-m', '--max-time'): o['max_time'] = float(argv[i+1]); i += 2
        elif a == '--compressed': i += 1
        elif a == '--no-fingerprint': o['no_fingerprint'] = True; i += 1
        elif a in ('-v', '--verbose'): o['verbose'] = True; i += 1
        elif a in ('-f', '--fail'): o['fail'] = True; i += 1
        elif a in ('-h', '--help'): print(__doc__); sys.exit(0)
        elif a.startswith('-') and len(a) > 1 and a not in ('-',):
            # combined short flags e.g. -sS, -si
            if not a.startswith('--') and all(c in 'sSikIvLfhj' for c in a[1:]):
                for c in a[1:]:
                    if c == 's': o['silent'] = True
                    elif c == 'i': o['include'] = True
                    elif c == 'k': o['insecure'] = True
                    elif c == 'I': o['head'] = True
                    elif c == 'v': o['verbose'] = True
                    elif c == 'L': o['follow'] = True
                    elif c == 'f': o['fail'] = True
                    elif c == 'j': o['json_mode'] = True
                i += 1
            else:
                die(f"unrecognized option {a} (use real curl for advanced flags)")
        else:
            o['urls'].append(a); i += 1
    if not o['urls']: die("no URL specified")
    if len(o['urls']) > 1: die("only one URL supported per call")
    return o

def main():
    args = parse_args(sys.argv[1:])
    url = args['urls'][0]

    # proxy default from env
    proxy = args['proxy'] or os.environ.get('PRIMP_PATCH_PROXY') or os.environ.get('HTTPS_PROXY') or None

    try:
        import primp
    except ImportError:
        die("primp not importable — install into the venv")

    imp = args['impersonate'] or os.environ.get('PCURL_IMPERSONATE') or 'chrome_146'
    kw = dict(impersonate=imp, timeout=args['max_time'] or 30.0,
              follow_redirects=args['follow'], max_redirects=10,
              verify=not args['insecure'], proxy=proxy)
    if args['no_fingerprint']:
        kw.pop('impersonate')

    # headers
    hdrs = {}
    auth = None
    for h in args['headers']:
        if ':' not in h: die(f"bad header: {h}")
        k, _, v = h.partition(':')
        hdrs[k.strip()] = v.strip()

    body = None
    if args['json_mode']:
        hdrs.setdefault('Content-Type', 'application/json')
        stdin = sys.stdin.read() if (not args['data'] or args['data'] == ['@-']) else '&'.join(args['data'])
        try: body = stdin if stdin else None
        except Exception: body = None
    elif args['data']:
        body = '&'.join(d for d in args['data'])

    method = (args['method'] or ('HEAD' if args['head'] else ('POST' if (body or args['forms']) else 'GET'))).upper()

    # multipart
    files = None
    if args['forms']:
        multipart = []
        for f in args['forms']:
            k, _, v = f.partition('=')
            if v.startswith('@'):
                p = v[1:]
                multipart.append((k, (os.path.basename(p), open(p, 'rb').read())))
            else:
                multipart.append((k, (None, v)))
        files = multipart

    try:
        client = primp.Client(**kw)
        req_kw = dict(headers=hdrs or None)
        if files is not None:
            req_kw['files'] = files
        elif args['json_mode'] and body:
            try:
                req_kw['json'] = _json.loads(body)
            except _json.JSONDecodeError:
                req_kw['data'] = body
        elif body:
            req_kw['data'] = body
            # curl semantics: -d implies form-urlencoded content type
            if not any(k.lower() == 'content-type' for k in (hdrs or {})):
                hdrs = dict(hdrs or {})
                hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
                req_kw['headers'] = hdrs
        resp = client.request(method, url, **req_kw)
    except Exception as e:
        msg = str(e)
        if 'timeout' in msg.lower(): die(msg, 28)
        if 'resolve' in msg.lower() or 'dns' in msg.lower() or 'name or service' in msg.lower(): die(msg, 6)
        die(msg, 7)

    status = resp.status_code
    rheaders = resp.headers

    out = sys.stdout.buffer if args['output'] in (None, '-') else open(args['output'], 'wb')
    if args['output'] not in (None, '-'):
        outf = open(args['output'], 'wb')
    else:
        outf = sys.stdout.buffer

    if not args['silent'] and args['output'] not in (None, '-'):
        # status line to stderr so piping stays clean
        pass

    if args['include']:
        lines = [f"HTTP/1.1 {status}"]
        for k, v in rheaders.items():
            lines.append(f"{k}: {v}")
        outf.write(('\r\n'.join(lines) + '\r\n\r\n').encode())
    elif not args['silent']:
        print(f"[pcurl] {method} {url} → {status} ({rheaders.get('content-type','')})", file=sys.stderr)

    content = resp.content
    if args['fail'] and status >= 400:
        sys.exit(22)
    outf.write(content)
    if args['output'] not in (None, '-'):
        outf.close()
    sys.exit(0 if status < 400 else (22 if args['fail'] else 0))

def cli():
    main()

if __name__ == '__main__':
    main()
