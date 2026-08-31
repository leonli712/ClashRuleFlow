#!/usr/bin/env python3
"""按策略组合并去重 Clash 规则集：全局扫描去除重复和被覆盖的规则，再按组输出"""
import re, sys, urllib.request, os
from datetime import datetime
from collections import OrderedDict

def parse_rulesets(ini_path):
    """返回 [(group, url_or_special), ...]，保留原始顺序"""
    result = []
    with open(ini_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith(';') or not line:
                continue
            m = re.match(r'^ruleset=(.+?),(.*)$', line)
            if m:
                group = m.group(1).strip()
                url = m.group(2).strip()
                if url:  # 跳过空行
                    result.append((group, url))
    return result

def download(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'clash-dedup/2.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode('utf-8', errors='ignore').splitlines()
    except Exception as e:
        print(f"  [WARN] 下载失败 {url}: {e}", file=sys.stderr)
        return []

def norm(d):
    return d.lower().rstrip('.')

def is_subdomain(domain, parent):
    d, p = norm(domain), norm(parent)
    return d == p or d.endswith('.' + p)

def main():
    ini_path = sys.argv[1] if len(sys.argv) > 1 else 'config.ini'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'rules_merged'

    rulesets = parse_rulesets(ini_path)
    print(f"找到 {len(rulesets)} 个 ruleset 引用\n")

    # 第一步：按原始顺序展开所有规则
    all_rules = []  # (rtype, val, extra, group, source_url)
    special_rules = []  # GEOIP/MATCH 等特殊规则，不下载

    for group, url in rulesets:
        if url.startswith('http'):
            print(f"下载 [{group}] {url}")
            lines = download(url)
            count = 0
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#') or line.startswith(';'):
                    continue
                parts = line.split(',')
                rtype = parts[0].strip().upper()
                val = parts[1].strip() if len(parts) > 1 else ''
                extra = parts[2].strip() if len(parts) > 2 else ''
                all_rules.append((rtype, val, extra, group))
                count += 1
            print(f"  -> {count} 条")
        else:
            # 特殊规则如 []GEOIP,CN / []MATCH
            special_rules.append((group, url))
            print(f"保留特殊规则 [{group}] {url}")

    total_raw = len(all_rules)
    print(f"\n展开后共 {total_raw} 条普通规则 + {len(special_rules)} 条特殊规则")

    # 第二步：全局去重（按原始顺序，保留第一次出现）
    seen_key = set()       # (rtype, val) —— 同类型同值，不管目标组，后面的都是死规则
    seen_full = set()      # (rtype, val, extra) —— 精确去重
    suffix_parents = []    # 已出现的 DOMAIN-SUFFIX
    deduped = []

    for rtype, val, extra, group in all_rules:
        key = (rtype, val)
        full = (rtype, val, extra)

        if full in seen_full:
            continue
        if key in seen_key:
            # 同类型同值但目标组不同 → 前面的先匹配，后面的是死规则
            seen_full.add(full)
            continue

        # 域名类：检测是否被前面的后缀覆盖
        if rtype in ('DOMAIN', 'DOMAIN-SUFFIX') and val:
            if any(is_subdomain(val, p) for p in suffix_parents):
                seen_key.add(key)
                seen_full.add(full)
                continue
            if rtype == 'DOMAIN-SUFFIX':
                suffix_parents.append(norm(val))

        seen_key.add(key)
        seen_full.add(full)
        deduped.append((rtype, val, extra, group))

    print(f"去重后共 {len(deduped)} 条 (减少 {total_raw - len(deduped)} 条, "
          f"精简 {((total_raw-len(deduped))/total_raw*100):.1f}%)")

    # 第三步：按策略组重新分组
    os.makedirs(out_dir, exist_ok=True)
    groups = OrderedDict()
    for rtype, val, extra, group in deduped:
        groups.setdefault(group, []).append((rtype, val, extra))

    print(f"\n按策略组输出:")
    group_files = {}
    for group, rules in groups.items():
        # 文件名：用组名的安全形式
        safe_name = re.sub(r'[^\w]', '_', group)
        fname = f"{safe_name}.list"
        fpath = os.path.join(out_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(f"# {group} | 合并去重后 {len(rules)} 条\n")
            f.write(f"# 来源: {os.path.basename(ini_path)}\n\n")
            for rtype, val, extra in rules:
                if extra:
                    f.write(f"{rtype},{val},{extra}\n")
                else:
                    f.write(f"{rtype},{val}\n")
        group_files[group] = fname
        print(f"  {group}: {len(rules)} 条 -> {fname}")

    # 第四步：生成新的 ini 规则段
    print(f"\n{'='*60}")
    print("生成的 ruleset 替换片段（用以下内容替换原 ini 中的规则集配置段）:")
    print('='*60)
    for group, fname in group_files.items():
        # 这里用你的 GitHub raw 地址前缀，需要替换成你自己的
        print(f'ruleset={group},https://raw.githubusercontent.com/leonli712/ClashRuleFlow/main/rules_merged/{fname}')
    # 特殊规则放在最后
    for group, url in special_rules:
        print(f'ruleset={group},{url}')

    # 同时保存到文件
    snippet_path = os.path.join(out_dir, 'ruleset_snippet.ini')
    with open(snippet_path, 'w', encoding='utf-8') as f:
        for group, fname in group_files.items():
            f.write(f'ruleset={group},https://raw.githubusercontent.com/leonli712/ClashRuleFlow/main/rules_merged/{fname}\n')
        for group, url in special_rules:
            f.write(f'ruleset={group},{url}\n')
    print(f"\n片段已保存到 {snippet_path}")

if __name__ == '__main__':
    main()
