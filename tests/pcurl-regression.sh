#!/bin/bash
# pcurl 回归测试套件 — 对齐 curl 语义
# 用法: bash pcurl-regression.sh
# 依赖: pcurl 在 PATH, httpbin.org 可达
PASS=0; FAIL=0
ck() { # ck <name> <expected> <actual>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "PASS  $1"
  else FAIL=$((FAIL+1)); echo "FAIL  $1  (期望=$2 实际=$3)"; fi
}
j() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# ── T0 基础 GET ──
r=$(pcurl -s https://api.github.com/zen 2>/dev/null); ck "T0a GET github zen 非空" ok "$([ -n "$r" ] && echo ok)"
code=$(pcurl -s -o /dev/null --max-time 20 https://httpbin.org/get 2>/dev/null; echo $?); ck "T0b GET httpbin exit=0" 0 "$code"

# ── T1 状态行到 stderr，body 到 stdout ──
err=$(pcurl https://api.github.com/zen 2>&1 >/dev/null | head -1); ck "T1 stderr 状态行格式" ok "$(echo "$err" | grep -q '^\[pcurl\] GET .* → 200' && echo ok)"
out=$(pcurl -s https://api.github.com/zen 2>/dev/null); ck "T1b -s 时 stderr 干净" 0 "$(pcurl -s https://api.github.com/zen 2>&1 >/dev/null | wc -l | tr -d ' ')"

# ── T2 -i 响应头 ──
h=$(pcurl -si https://httpbin.org/get 2>/dev/null | head -1 | tr -d "\r"); ck "T2 -i 首行 HTTP/1.1 200" "HTTP/1.1 200" "$h"

# ── T3 POST JSON（显式 -H） ──
r=$(pcurl -s -X POST https://httpbin.org/post -H 'Content-Type: application/json' -d '{"k":"v","n":7}' 2>/dev/null | j "d['json']"); ck "T3 POST JSON 回显" "{'k': 'v', 'n': 7}" "$r"

# ── T4 表单 -d 自动 CT ──
r=$(pcurl -s -d 'a=1&b=2' https://httpbin.org/post 2>/dev/null | j "d['form']"); ck "T4 表单回显" "{'a': '1', 'b': '2'}" "$r"
r=$(pcurl -s -d 'a=1&b=2' https://httpbin.org/post 2>/dev/null | j "d['headers']['Content-Type']"); ck "T4b 自动 CT" "application/x-www-form-urlencoded" "$r"

# ── T5 显式 CT 不被覆盖 ──
r=$(pcurl -s -d 'x=1' -H 'Content-Type: text/plain' https://httpbin.org/post 2>/dev/null | j "d['headers']['Content-Type']"); ck "T5 显式 CT 保留" "text/plain" "$r"

# ── T6 多个 -d 用 & 拼接 ──
r=$(pcurl -s -d 'a=1' -d 'b=2' https://httpbin.org/post 2>/dev/null | j "d['form']"); ck "T6 多 -d 拼接" "{'a': '1', 'b': '2'}" "$r"

# ── T7 -j stdin JSON ──
r=$(echo '{"a":1}' | pcurl -s -j https://httpbin.org/post 2>/dev/null | j "d['json']"); ck "T7 -j stdin JSON" "{'a': 1}" "$r"
r=$(pcurl -s -j -d '{"k":"v"}' https://httpbin.org/post 2>/dev/null | j "d['json']"); ck "T7b -j -d JSON" "{'k': 'v'}" "$r"
r=$(pcurl -s -j https://httpbin.org/post 2>/dev/null | j "d['headers']['Content-Type']"); ck "T7c -j 自动 CT" "application/json" "$r"

# ── T8 自定义头 ──
r=$(pcurl -s -H 'X-Test: hello123' https://httpbin.org/get 2>/dev/null | j "d['headers']['X-Test']"); ck "T8 自定义头透传" "hello123" "$r"

# ── T9 -o 落盘 ──
pcurl -s -o /tmp/pc_t9.bin https://api.github.com/zen 2>/dev/null; s=$(wc -c < /tmp/pc_t9.bin); rm -f /tmp/pc_t9.bin
ck "T9 -o 落盘非空" ok "$([ "$s" -gt 0 ] && echo ok)"

# ── T10 重定向 ──
r=$(pcurl -sL -o /dev/null -w '' "https://httpbin.org/redirect/2" 2>/dev/null; echo $?)
r=$(pcurl -sL https://httpbin.org/redirect/2 2>/dev/null >/dev/null; echo $?); ck "T10 -L 跟随重定向" 0 "$r"

# ── T11 方法 ──
r=$(pcurl -s -X PUT https://httpbin.org/put -d 'x=1' -o /dev/null 2>/dev/null; echo $?); ck "T11a PUT" 0 "$r"
r=$(pcurl -s -X DELETE https://httpbin.org/delete -o /dev/null 2>/dev/null; echo $?); ck "T11b DELETE" 0 "$r"
r=$(pcurl -s -I https://httpbin.org/get 2>/dev/null | head -1 | tr -d "\r"); ck "T11c -I HEAD(隐含-i)" "HTTP/1.1 200" "$r"

# ── T12 --fail ──
pcurl -sf https://httpbin.org/status/404 >/dev/null 2>&1; ck "T12a --fail 404 exit=22" 22 $?
pcurl -s https://httpbin.org/status/404 >/dev/null 2>&1; ck "T12b 无 --fail 时 404 exit=0" 0 $?
pcurl -sf https://httpbin.org/status/200 >/dev/null 2>&1; ck "T12c --fail 200 exit=0" 0 $?

# ── T13 -k 自签 ──
pcurl -sk -o /dev/null https://self-signed.badssl.com/ 2>/dev/null; ck "T13 -k 自签通过" 0 $?
pcurl -s -o /dev/null https://self-signed.badssl.com/ >/dev/null 2>&1; c=$?; ck "T13b 无 -k 自签失败(7或35)" ok "$([ $c -ne 0 ] && echo ok)"

# ── T14 UA 指纹 ──
r=$(pcurl -s https://httpbin.org/user-agent 2>/dev/null | j "d['user-agent']"); ck "T14a UA=Chrome 指纹" ok "$(echo "$r" | grep -q 'Mozilla/5.0' && echo "$r" | grep -q 'Chrome/' && echo ok)"
r=$(pcurl -s --no-fingerprint https://httpbin.org/user-agent 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['user-agent'] is None)")
ck "T14b --no-fingerprint UA=null" "True" "$r"

# ── T15 环境变量代理 ──
r=$(PRIMP_PATCH_PROXY=http://100.88.88.88:7890 pcurl -s -o /dev/null "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d" 2>/dev/null; echo $?); ck "T15 env 代理可达 yahoo" 0 "$r"

# ── T16 错误处理 ──
pcurl https://nonexistent-domain-abc123xyz.invalid/ >/dev/null 2>&1; c=$?; ck "T16a DNS 失败 exit∈{6,7}" ok "$([ $c -eq 6 ] || [ $c -eq 7 ] && echo ok)"
pcurl -s --max-time 3 https://httpbin.org/delay/15 >/dev/null 2>&1; ck "T16b 超时 exit=28" 28 $?
pcurl -s --bogus-flag https://x/ >/dev/null 2>&1; ck "T16c 未知选项 exit=2" 2 $?
pcurl >/dev/null 2>&1; ck "T16d 缺 URL exit=2" 2 $?

# ── T17 --impersonate ──
r=$(pcurl -s --impersonate firefox https://httpbin.org/user-agent 2>/dev/null | j "d['user-agent']"); ck "T17a firefox 档位" ok "$(echo "$r" | grep -qi 'Firefox/' && echo ok)"
pcurl -s --impersonate bogus_xyz https://httpbin.org/get >/dev/null 2>&1; ck "T17b 非法档位报错" 2 $?

# ── T18 组合短旗标 ──
h=$(pcurl -si https://httpbin.org/get 2>/dev/null | head -1 | tr -d "\r"); ck "T18 组合旗标 -si" "HTTP/1.1 200" "$h"

# ── T19 multipart ──
echo "hello-pcurl" > /tmp/pc_t19.txt
r=$(pcurl -s -F 'f=@/tmp/pc_t19.txt' -F 'note=hi' https://httpbin.org/post 2>/dev/null | j "(d['form']['note'], 'hello-pcurl' in (d.get('files') or {}).get('f',''))")
ck "T19 multipart 字段+文件" "('hi', True)" "$r"; rm -f /tmp/pc_t19.txt

echo "──────────────────────────"
echo "总计: $PASS PASS / $FAIL FAIL"
[ $FAIL -eq 0 ] && echo "全部通过 ✓" || echo "存在失败 ✗"
exit $FAIL
