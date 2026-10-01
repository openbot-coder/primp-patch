#!/usr/bin/env python3
"""pcurl — curl-like client backed by primp (rnet core, browser TLS/JA3 fingerprint).

Drop-in replacement for the common curl use cases. Anything not recognized
falls back to real curl (with --no-fingerprint passthrough disabled).

Usage:
  pcurl [options] <url>
Options (curl-compatible subset):
  -X, --method <M>        HTTP method (default GET; POST auto with -d)
  -d, --data <data>       request body (repeatable, joined with &)
      --data-raw <data>   same as -d (@file NOT supported)
  -H, --header <h>        extra header "Name: value" (repeatable)
  -F, --form <f>          multipart field "k=v" or "k=@file"
  -o, --output <file>     write body to file (- = stdout)
  -L, --location          follow redirects
  -k, --insecure          accept invalid certs
  -s, --silent            suppress status line
  -i, --include           include response headers in output
  -I, --head              HEAD request
  -j, --json              shorthand: -H content-type:application/json -d @-
      --impersonate <p>   primp profile (chrome_146 default; primp 2.x also: chrome_145, firefox, safari, edge)
      --proxy <url>       proxy for this request (default: $PRIMP_PATCH_PROXY/$HTTPS_PROXY)
      --max-time <sec>    total timeout
      --compressed        accepted for curl compat (primp always handles)
      --no-fingerprint    plain HTTP (no TLS impersonation)
  -v, --verbose           print request summary to stderr
  -h, --help              this help
Exit codes follow curl: 0 ok, 6 host resolve, 7 connect, 22 --fail, 28 timeout.
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
    # like curl -o: also support -w style? keep simple
    sys.exit(0 if status < 400 else (22 if args['fail'] else 0))

if __name__ == '__main__':
    main()


def cli():
    main()

if __name__ == '__main__':
    main()
