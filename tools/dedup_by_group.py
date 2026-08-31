#!/usr/bin/env python3
"""按策略组合并去重 Clash 规则集，并生成完整的 Router_merged.ini"""
import re, sys, urllib.request, os
from datetime import datetime
from collections import OrderedDict

def parse_ini(ini_path):
    """读取 ini，分离头部（非 ruleset 部分）和 ruleset 列表"""
    header_lines = []
    rulesets = []
    in_rules_section = False

    with open(ini_path, encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('ruleset='):
                in_rules_section = True
                m = re.match(r'^ruleset=(.+?),(.*)$', stripped)
                if m:
                    group = m.group(1).strip()
                    url = m.group(2).strip()
                    if url:
                        rulesets.append((group, url))
            else:
                if not in_rules_section:
                    header_lines.append(line.rstrip('\n'))
                # 跳过 ruleset 段中间的空行和注释

    return header_lines, rulesets

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
    ini_path = sys.argv[1] if len(sys.argv) > 1 else 'Router.ini'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'rules_merged'
    merged_ini_name = sys.argv[3] if len(sys.argv) > 3 else 'Router_merged.ini'

    repo_raw_prefix = 'https://raw.githubusercontent.com/leonli712/ClashRuleFlow/main'

    print(f"读取 {ini_path}...")
    header_lines, rulesets = parse_ini(ini_path)
    print(f"头部 {len(header_lines)} 行，规则集引用 {len(rulesets)} 个\n")

    # 展开所有规则
    all_rules = []
    special_rules = []

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
            special_rules.append((group, url))
            print(f"保留特殊规则 [{group}] {url}")

    total_raw = len(all_rules)
    print(f"\n展开后共 {total_raw} 条普通规则 + {len(special_rules)} 条特殊规则")

    # 全局去重
    seen_key = set()
    seen_full = set()
    suffix_parents = []
    deduped = []

    for rtype, val, extra, group in all_rules:
        key = (rtype, val)
        full = (rtype, val, extra)

        if full in seen_full:
            continue
        if key in seen_key:
            seen_full.add(full)
            continue

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

    # 按组输出 list 文件
    os.makedirs(out_dir, exist_ok=True)
    groups = OrderedDict()
    for rtype, val, extra, group in deduped:
        groups.setdefault(group, []).append((rtype, val, extra))

    print(f"\n按策略组输出:")
    group_files = {}
    for group, rules in groups.items():
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

    # 生成完整的 Router_merged.ini
    print(f"\n生成 {merged_ini_name}...")
    with open(merged_ini_name, 'w', encoding='utf-8') as f:
        # 写入头部
        for line in header_lines:
            f.write(line + '\n')

        # 写入规则集段标题
        f.write('\n; ==========【规则集配置（自动去重合并）】 ==========\n')

        # 写入合并后的 ruleset 引用
        for group, fname in group_files.items():
            f.write(f'ruleset={group},{repo_raw_prefix}/{out_dir}/{fname}\n')

        # 写入特殊规则
        for group, url in special_rules:
            f.write(f'ruleset={group},{url}\n')

    print(f"已生成 {merged_ini_name}")

    # 同时保存 snippet 供参考
    snippet_path = os.path.join(out_dir, 'ruleset_snippet.ini')
    with open(snippet_path, 'w', encoding='utf-8') as f:
        for group, fname in group_files.items():
            f.write(f'ruleset={group},{repo_raw_prefix}/{out_dir}/{fname}\n')
        for group, url in special_rules:
            f.write(f'ruleset={group},{url}\n')
    print(f"规则片段已保存到 {snippet_path}")

if __name__ == '__main__':
    main()
