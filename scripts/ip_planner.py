#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ip_planner.py —— 网络项目 VLSM 自动划址器（由 network-deploy 技能阶段 4 调用）

功能：
    根据各 VLAN 终端数、互联链路数、loopback 需求，从基础网段自动做 VLSM 划址，
    输出"网段/掩码/网关/可用范围"表，并自动分配：
      - 各 VLAN 网关（.254，VRRP 虚地址同值）
      - 互联链路 /30 网段
      - 设备 loopback 地址
      - DHCP 池范围（.101–.254，网关 .254）
    支持两种用法：
      1. 读需求 JSON（-i），输出划址结果 JSON（-o）与人类可读表（stdout）
      2. 生成项目模型片段（--model），直接拼入 model_schema.json 的 vlans/links 字段

用法：
    python ip_planner.py -i 需求.json                    # 打印划址表
    python ip_planner.py -i 需求.json -o 划址结果.json   # 同时落盘 JSON
    python ip_planner.py -i 需求.json --model 项目模型.json  # 输出模型片段（vlans/links）并合并
    python ip_planner.py --demo                          # 打印内置示例

需求 JSON 结构（minimal）：
{
  "base_network": "10.10.0.0/16",          # 划址总网段
  "management_net": "10.10.0.0/24",        # 管理网段（可选，须在 base 内，占 1 个 /24）
  "loopbacks": ["DSW1", "DSW2", "AR1"],    # 需要 loopback 的设备
  "vlans": [
    {"name": "STAFF", "hosts": 500},
    {"name": "VOICE", "hosts": 100},
    {"name": "DMZ", "hosts": 30}
  ],
  "links": 5,                              # 互联链路条数（每条约 /30）
  "dhcp": ["STAFF"]                        # 哪些 VLAN 需要 DHCP 池（默认全部三层业务 VLAN）
}

划址策略（与 skill 阶段 4 约定一致）：
- VLAN 网段：主机数向上取 2 的幂 +2（网络号/广播），最小 /24；
- 网关：网段 .254；VRRP 虚地址=网关；
- 互联：独立 /24 网段内连续 /30（默认 10.99.0.0/24，可用 --link-net 指定）；
- loopback：独立网段默认 1.1.1.0/24 按序分配（可用 --loopback-net 指定）；
- DHCP 池：.101–.254，网关 .254（与 verify.md 验收口径一致）。
"""

import argparse
import json
import ipaddress


def next_power2(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def subnet_of(a, b):
    """a 是否为 b 的子网（兼容 strict 边界）"""
    return a.subnet_of(b)


def carve(net, prefix, occupied):
    """从 net 切出第一个不与 occupied 重叠的 /prefix 子网。
    返回 (子网, 剩余可用网段列表)；找不到返回 (None, [])。"""
    # 若 net 完全被某个已占用网段包含 → 整块丢弃
    for occ in occupied:
        if net.subnet_of(occ):
            return None, []
    if net.prefixlen == prefix:
        # 目标前缀：检查是否与已占用网段重叠
        for occ in occupied:
            if net.overlaps(occ):
                return None, []
        return net, []
    if net.prefixlen > prefix:
        return None, []  # 网段已小于目标，不可能再切
    left, right = net.subnets()
    sub, rem = carve(left, prefix, occupied)
    if sub is not None:
        return sub, [right] + rem
    sub, rem2 = carve(right, prefix, occupied)
    if sub is not None:
        return sub, [left] + rem2
    return None, []


def vlsm_allocate(base, demands, min_prefix=24, occupied=None):
    """在 base 网段内按主机数降序 VLSM 分配，跳过 occupied 网段。
    返回 [(name, network, hosts, gw), ...]"""
    occupied = occupied or []
    items = []
    for d in demands:
        hosts = int(d.get("hosts", 10))
        need = max(hosts + 2, 2 ** (32 - min_prefix))
        prefix_bits = next_power2(need).bit_length() - 1
        # 前缀长度：位数越多网段越小。主机数多 → 网段大 → 前缀短。
        prefix = 32 - prefix_bits
        if prefix > min_prefix:  # 需求网段比 /min_prefix 更小 → 放大到最小允许值
            prefix = min_prefix
        items.append((d["name"], hosts, prefix))
    items.sort(key=lambda x: x[2])  # 大网段（前缀短）先分

    pool = [ipaddress.ip_network(base, strict=False)]
    results = []
    for name, hosts, prefix in items:
        chosen = None
        new_pool = []
        for net in pool:
            if chosen is None and net.prefixlen <= prefix:
                sub, rem = carve(net, prefix, occupied)
                if sub is not None:
                    chosen = sub
                    new_pool.extend(rem)
                    continue
            new_pool.append(net)
        if chosen is None:
            raise ValueError("网段不足：无法为 %s 分配 /%d 网段" % (name, prefix))
        net_list = list(chosen.hosts())
        gw = net_list[-2]
        results.append({
            "name": name,
            "hosts": hosts,
            "network": str(chosen),
            "net": str(chosen),
            "prefix": chosen.prefixlen,
            "mask": str(chosen.netmask),
            "gw": str(gw),
            "usable": "%s-%s" % (net_list[0], net_list[-1]),
        })
        pool = new_pool
    return results


def alloc_links(link_net, count):
    base = ipaddress.ip_network(link_net, strict=False)
    out = []
    for i, net in enumerate(base.subnets(prefixlen_diff=6)):  # 例如 /24 -> /30
        if i >= count:
            break
        h = list(net.hosts())
        out.append({"net": str(net), "a": str(h[0]), "b": str(h[1])})
    return out


def alloc_loopbacks(loopback_net, names):
    base = ipaddress.ip_network(loopback_net, strict=False)
    hosts = list(base.hosts())
    if len(hosts) < len(names):
        raise ValueError("loopback 网段 %s 地址不足（需 %d 个）" % (loopback_net, len(names)))
    return [{"hostname": n, "loopback": str(hosts[i])} for i, n in enumerate(names)]


def build_plan(req):
    base = req.get("base_network", "10.10.0.0/16")
    occupied = []
    mgmt = req.get("management_net")
    if mgmt:
        occupied.append(ipaddress.ip_network(mgmt, strict=False))
    vlan_res = vlsm_allocate(base, req.get("vlans", []), occupied=occupied)
    link_net = req.get("link_net", "10.99.0.0/24")
    links = alloc_links(link_net, int(req.get("links", 0)))
    loopback_net = req.get("loopback_net", "1.1.1.0/24")
    loopbacks = alloc_loopbacks(loopback_net, req.get("loopbacks", []))

    dhcp_names = req.get("dhcp", [v["name"] for v in req.get("vlans", [])])
    for v in vlan_res:
        net = ipaddress.ip_network(v["net"], strict=False)
        hosts = list(net.hosts())
        if len(hosts) >= 254:
            v["dhcp_range"] = "%s-%s" % (hosts[100], hosts[-2])  # .101-.254
        else:
            mid = max(len(hosts) // 2, 2)
            v["dhcp_range"] = "%s-%s" % (hosts[mid], hosts[-2])
        v["dhcp"] = v["name"] in dhcp_names

    return {
        "base_network": base,
        "vlans": vlan_res,
        "links": links,
        "loopbacks": loopbacks,
    }


def to_model_fragment(plan):
    vlans = []
    for v in plan["vlans"]:
        item = {
            "id": None,  # VLAN ID 由 AI 按阶段 4 规则分配（10/20/30…）
            "name": v["name"],
            "net": v["network"],
            "gw": v["gw"],
            "vrrp": True,
            "vrrp_vrid": None,
            "vrrp_primary": None,
            "dhcp_range": v.get("dhcp_range"),
        }
        vlans.append(item)
    links = [
        {"a": None, "b": None, "type": "static", "mode": "access",
         "vlan": None, "net": l["net"]} for l in plan["links"]
    ]
    return {"vlans": vlans, "links": links}


def print_table(plan):
    print("== VLSM 划址结果 ==")
    print("%-12s %-18s %-6s %-16s %-22s %s" % ("VLAN", "网段", "掩码", "网关", "可用范围", "DHCP池"))
    for v in plan["vlans"]:
        print("%-12s %-18s %-6s %-16s %-22s %s" % (
            v["name"], v["network"], v["prefix"], v["gw"], v["usable"],
            v.get("dhcp_range", "-") if v.get("dhcp") else "-"))
    print("\n== 互联链路 /30 ==")
    for i, l in enumerate(plan["links"], 1):
        print("链路%d: %s  A=%s  B=%s" % (i, l["net"], l["a"], l["b"]))
    print("\n== Loopback ==")
    for lb in plan["loopbacks"]:
        print("%-10s %s" % (lb["hostname"], lb["loopback"]))


def main():
    ap = argparse.ArgumentParser(description="网络项目 VLSM 自动划址器")
    ap.add_argument("-i", "--input", help="需求 JSON 路径")
    ap.add_argument("-o", "--output", help="划址结果 JSON 输出路径")
    ap.add_argument("--model", help="输出模型片段并合并进指定项目模型 JSON")
    ap.add_argument("--demo", action="store_true", help="打印内置示例")
    args = ap.parse_args()

    if args.demo or not args.input:
        demo = {
            "base_network": "10.10.0.0/16",
            "management_net": "10.10.0.0/24",
            "loopbacks": ["DSW1", "DSW2", "AR1", "AR2"],
            "vlans": [
                {"name": "STAFF", "hosts": 500},
                {"name": "VOICE", "hosts": 100},
                {"name": "DMZ", "hosts": 30},
            ],
            "links": 3,
            "dhcp": ["STAFF", "VOICE"],
        }
        plan = build_plan(demo)
        print_table(plan)
        print("\n[提示] 以上为内置示例。实际使用请用 -i 指定需求 JSON。")
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)
            print("已写出 -> %s" % args.output)
        return

    with open(args.input, "r", encoding="utf-8") as f:
        req = json.load(f)
    plan = build_plan(req)
    print_table(plan)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        print("已写出 -> %s" % args.output)

    if args.model:
        frag = to_model_fragment(plan)
        with open(args.model, "r", encoding="utf-8") as f:
            model = json.load(f)
        model.setdefault("vlans", []).extend(frag["vlans"])
        model.setdefault("links", []).extend(frag["links"])
        with open(args.model, "w", encoding="utf-8") as f:
            json.dump(model, f, ensure_ascii=False, indent=2)
        print("已合并 vlans/links 片段 -> %s" % args.model)


if __name__ == "__main__":
    main()
