#!/usr/bin/env python3
"""生成 Clash for Windows / Clash Meta 配置：Inside.yml（局域网）和 Outside.yml（外网）"""
import re, sys, urllib.request, yaml
from collections import OrderedDict

# ========== 基础配置（Inside 和 Outside 共用） ==========
BASE_CONFIG = """
mixed-port: 7890
allow-lan: true
bind-address: '*'
mode: rule
log-level: info
external-controller: '127.0.0.1:9090'
unified-delay: true
hosts:
    mtalk.google.com: 108.177.125.188
    raw.githubusercontent.com: 151.101.76.133
dns:
    enable: true
    ipv6: true
    listen: '127.0.0.1:5334'
    default-nameserver: [180.184.1.1, 119.29.29.29, 223.5.5.5]
    proxy-server-nameserver: ['https://223.5.5.5/dns-query', 'https://doh.pub/dns-query']
    enhanced-mode: fake-ip
    fake-ip-range: 198.18.0.1/16
    use-hosts: true
    use-system-hosts: true
    fake-ip-filter: ['*.market.xiaomi.com', '*.n.n.srv.nintendo.net', +.stun.playstation.net, 'xbox.*.*.microsoft.com', '*.msftncsi.com', '*.msftconnecttest.com', WORKGROUP, '*.lan', 'stun.*.*.*', 'stun.*.*', time.windows.com, time.nist.gov, time.apple.com, time.asia.apple.com, '*.ntp.org.cn', '*.openwrt.pool.ntp.org', time1.cloud.tencent.com, time.ustc.edu.cn, pool.ntp.org, ntp.ubuntu.com, '*.*.xboxlive.com', speedtest.cros.wr.pvp.net, stun.services.mozilla1.com, ntp.nasa.gov, captive.apple.com]
    nameserver: ['https://223.6.6.6/dns-query', 'https://120.53.53.53/dns-query', 'tls://223.5.5.5:853']
"""
import os

# ========== 代理节点配置（全部从环境变量读取，不硬编码） ==========
INSIDE_PROXY = {
    "name": "旁路由",
    "type": "socks5",
    "server": os.environ["INSIDE_SERVER"],
    "port": int(os.environ["INSIDE_PORT"]),
    "udp": True,
    "username": os.environ["PROXY_USERNAME"],
    "password": os.environ["PROXY_PASSWORD"],
    "skip-cert-verify": True,
}

OUTSIDE_PROXY = {
    "name": "旁路由",
    "type": "socks5",
    "server": os.environ["OUTSIDE_SERVER"],
    "port": int(os.environ["OUTSIDE_PORT"]),
    "udp": True,
    "username": os.environ["PROXY_USERNAME"],
    "password": os.environ["PROXY_PASSWORD"],
    "skip-cert-verify": True,
}

# ========== 策略组默认行为 ==========
DIRECT_GROUPS = {"国内流量", "LocalAreaNetwork", "UnBan", "GoogleCN", "SteamCN",
                 "ChinaDomain", "ChinaCompanyIp", "ChinaIp", "ChinaIpV6"}
REJECT_GROUPS = {"全球拦截", "BanAD", "BanProgramAD", "BanEasyList", "BanEasyPrivacy"}
# ============================================================

def parse_rulesets(ini_path):
    rulesets = []
    with open(ini_path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s.startswith('ruleset='):
                m = re.match(r'^ruleset=(.+?),(.*)$', s)
                if m:
                    g, u = m.group(1).strip(), m.group(2).strip()
                    if u:
                        rulesets.append((g, u))
    return rulesets

def download(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'clash-cfw-gen/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode('utf-8', errors='ignore').splitlines()
    except Exception as e:
        print(f"  [WARN] 下载失败 {url}: {e}", file=sys.stderr)
        return []

def norm(d):
    return d.lower().rstrip('.')

def is_subdomain(d, p):
    d, p = norm(d), norm(p)
    return d == p or d.endswith('.' + p)

def dedup(all_rules):
    seen_key, seen_full, suffix = set(), set(), []
    result = []
    for rt, v, ex, g in all_rules:
        key, full = (rt, v), (rt, v, ex)
        if full in seen_full:
            continue
        if key in seen_key:
            seen_full.add(full)
            continue
        if rt in ('DOMAIN', 'DOMAIN-SUFFIX') and v:
            if any(is_subdomain(v, p) for p in suffix):
                seen_key.add(key); seen_full.add(full)
                continue
            if rt == 'DOMAIN-SUFFIX':
                suffix.append(norm(v))
        seen_key.add(key); seen_full.add(full)
        result.append((rt, v, ex, g))
    return result

def build_proxy_groups(group_names):
    pgs = []
    for g in group_names:
        if g in REJECT_GROUPS:
            pgs.append({"name": g, "type": "select", "proxies": ["REJECT", "DIRECT", "旁路由"]})
        elif g in DIRECT_GROUPS:
            pgs.append({"name": g, "type": "select", "proxies": ["DIRECT", "旁路由"]})
        else:
            pgs.append({"name": g, "type": "select", "proxies": ["旁路由", "DIRECT"]})
    pgs.append({"name": "漏网之鱼", "type": "select", "proxies": ["旁路由", "DIRECT"]})
    return pgs

def build_rules(deduped, special_rules):
    rules = []
    for rt, v, ex, g in deduped:
        if ex:
            rules.append(f"{rt},{v},{ex},{g}")
        else:
            rules.append(f"{rt},{v},{g}")
    for g, u in special_rules:
        if u.startswith('[]'):
            content = u[2:]
            if ',' in content:
                rules.append(f"{content},{g}")
            else:
                rules.append(f"{content},{g}")
    return rules

def generate_config(proxy, group_names, deduped, special_rules, output_path):
    config = yaml.safe_load(BASE_CONFIG)
    config["proxies"] = [proxy]
    config["proxy-groups"] = build_proxy_groups(group_names)
    config["rules"] = build_rules(deduped, special_rules)

    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"已生成 {output_path} ({len(config['rules'])} 条规则)")

def main():
    ini_path = sys.argv[1] if len(sys.argv) > 1 else 'PC.ini'
    inside_path = sys.argv[2] if len(sys.argv) > 2 else 'Inside.yml'
    outside_path = sys.argv[3] if len(sys.argv) > 3 else 'Outside.yml'

    print(f"读取 {ini_path}...")
    rulesets = parse_rulesets(ini_path)
    print(f"找到 {len(rulesets)} 个规则集引用\n")

    all_rules, special_rules = [], []
    for group, url in rulesets:
        if url.startswith('http'):
            print(f"下载 [{group}] {url}")
            cnt = 0
            for line in download(url):
                line = line.strip()
                if not line or line.startswith('#') or line.startswith(';'):
                    continue
                parts = line.split(',')
                rt = parts[0].strip().upper()
                v = parts[1].strip() if len(parts) > 1 else ''
                ex = parts[2].strip() if len(parts) > 2 else ''
                all_rules.append((rt, v, ex, group))
                cnt += 1
            print(f"  -> {cnt} 条")
        else:
            special_rules.append((group, url))
            print(f"保留特殊规则 [{group}] {url}")

    total = len(all_rules)
    print(f"\n展开 {total} 条 + {len(special_rules)} 特殊")
    deduped = dedup(all_rules)
    print(f"去重后 {len(deduped)} 条 (减少 {total-len(deduped)}, 精简 {(total-len(deduped))/total*100:.1f}%)")

    group_names = list(OrderedDict.fromkeys(g for _, _, _, g in deduped))

    print("\n--- 生成配置 ---")
    generate_config(INSIDE_PROXY, group_names, deduped, special_rules, inside_path)
    generate_config(OUTSIDE_PROXY, group_names, deduped, special_rules, outside_path)

if __name__ == '__main__':
    main()
