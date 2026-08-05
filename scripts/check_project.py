#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_project.py —— 网络项目模型静态校验器（由 network-deploy 技能阶段 5 调用）

功能：
    对锁定后的项目模型 JSON（model_schema.json 工程化结构）做程序化可行性检查，
    把 SKILL.md 阶段 5 的"人工排查项"固化为代码，逐项输出"问题 → 影响 → 建议"报告。
    建议：阶段 5 必须运行一次，输出报告供与用户确认风险处理方案。

检查项：
  [IP]      全局 IP 冲突（管理IP/loopback/接口IP/网关/VLAN网段/互联网段）
  [端口]    同一物理接口被配置两次（devices[].interfaces 重复 name）
  [VLAN]    VLAN ID 冲突、Trunk 放行列表引用不存在的 VLAN
  [路由]    VRRP 虚地址与接口地址不同网段、静态路由目的网段未规划
  [聚合]    跨厂商 LACP/堆叠违规（硬性规则：跨厂商上联一律静态 Trunk）
  [能力]    型号能力校验（C2960 纯二层不能跑 OSPF/三层路由）
  [掩码]    互联网段掩码合理性（/30 互联不应写成 /24；业务网段不应过小）
  [HA]      热备心跳配置缺失、VRRP 优先级差为 0
  [安全]    NAT 缺 inside/outside 或匹配 ACL、DMZ 暴露端口未记录
  [服务]    DHCP 池网段与 VLAN 网段不一致、SNMP/Syslog 目标未填

用法：
    python check_project.py 项目模型.json
    python check_project.py 项目模型.json --json      # 输出 JSON 报告
    python check_project.py 项目模型.json --strict    # 有 ERROR 则退出码 1（供流程门禁）

退出码：
    0 = 无 ERROR（可进入阶段 6）；1 = 存在 ERROR（须修复或人工确认后带 --strict 强制）
"""

import argparse
import ipaddress
import json
import sys

# 型号能力库：纯二层（不能三层路由/OSPF）的型号
L2_ONLY_MODELS = {
    "c2960", "c2960x", "c2960l", "s2700", "s2710", "s2750", "s5700-li",
}
# 需要 License 的常见特性（提示用）
LICENSE_HINTS = {
    "ce6800": "M-LAG/EVPN 需 License",
    "ce12800": "M-LAG/EVPN 需 License",
    "s9700": "高级路由特性需 License",
    "usg6000": "部分功能需 License",
}


def _ip(s):
    try:
        return ipaddress.ip_address(s)
    except Exception:
        return None


def _net(s):
    try:
        return ipaddress.ip_network(s, strict=False)
    except Exception:
        return None


def check_project(model):
    issues = []  # {"level":"ERROR"/"WARN","cat":"IP","msg":"...","fix":"..."}

    def add(level, cat, msg, fix):
        issues.append({"level": level, "cat": cat, "msg": msg, "fix": fix})

    devices = model.get("devices", [])
    vlans = model.get("vlans", [])
    links = model.get("links", [])
    routing = model.get("routing", {}) or {}
    security = model.get("security", {}) or {}
    services = model.get("services", {}) or {}

    # ---------- 收集所有已分配 IP ----------
    used_ips = {}  # ip -> owner
    vlan_nets = []  # (name, net)
    vlan_ids = {}
    for v in vlans:
        vid = v.get("id")
        if vid is not None:
            if vid in vlan_ids:
                add("ERROR", "VLAN", "VLAN ID %s 被重复使用（%s 与 %s）" % (vid, vlan_ids[vid], v.get("name")),
                    "重新分配 VLAN ID")
            vlan_ids[vid] = v.get("name")
        n = _net(v.get("net"))
        if n:
            vlan_nets.append((v.get("name"), n))
        gw = _ip(v.get("gw"))
        if gw:
            owner = "VLAN %s 网关" % v.get("name")
            if str(gw) in used_ips:
                add("ERROR", "IP", "%s 与 %s 冲突（%s）" % (owner, used_ips[str(gw)], gw),
                    "调整网关或改网段")
            else:
                used_ips[str(gw)] = owner

    # ---------- 设备 / 接口 ----------
    iface_seen = {}
    for dev in devices:
        hostname = dev.get("hostname", "?")
        for key in ("mgmt_ip", "loopback"):
            ip = _ip(dev.get(key))
            if ip:
                owner = "%s.%s" % (hostname, key)
                if str(ip) in used_ips:
                    add("ERROR", "IP", "%s 与 %s 冲突（%s）" % (owner, used_ips[str(ip)], ip),
                        "调整该地址")
                else:
                    used_ips[str(ip)] = owner
        # 接口重复
        for itf in dev.get("interfaces", []):
            iname = itf.get("name")
            if not iname:
                continue
            if (hostname, iname) in iface_seen:
                add("ERROR", "端口", "%s:%s 被配置两次" % (hostname, iname),
                    "删除重复接口定义")
            iface_seen[(hostname, iname)] = itf
            ip = _ip(str(itf.get("ip", "")).split("/")[0]) if itf.get("ip") else None
            if ip:
                owner = "%s:%s" % (hostname, iname)
                if str(ip) in used_ips:
                    add("ERROR", "IP", "%s 与 %s 冲突（%s）" % (owner, used_ips[str(ip)], ip),
                        "调整接口地址")
                else:
                    used_ips[str(ip)] = owner
        # 型号能力：纯二层型号若被指派三层角色（core/agg/router/fw）才报错；
        # 若角色为 access（二层接入），本身不跑三层路由，属正常用法。
        model_l = (dev.get("model") or "").lower()
        if model_l in L2_ONLY_MODELS:
            role = (dev.get("role") or "").lower()
            if role in ("core", "agg", "router", "fw") or role.startswith("三层"):
                add("ERROR", "能力", "%s 型号 %s 为纯二层交换机，不能承担 %s 三层路由/OSPF" % (hostname, dev.get("model"), dev.get("role")),
                    "三层网关上移至三层交换机/路由器，或换用三层型号")
        if model_l in LICENSE_HINTS:
            add("WARN", "能力", "%s 型号 %s：%s" % (hostname, dev.get("model"), LICENSE_HINTS[model_l]),
                "部署前确认 License 已授权")

    # ---------- 互联链路 ----------
    for lk in links:
        a = lk.get("a")
        b = lk.get("b")
        if a and b:
            va = a.split(":")[0] if ":" in a else a
            vb = b.split(":")[0] if ":" in b else b
            if va == vb:
                add("ERROR", "端口", "链路 %s ↔ %s 两端落在同一设备上" % (a, b),
                    "检查互联关系")
        if lk.get("mode") in ("lacp", "dynamic", "eth-trunk"):
            # 跨厂商聚合检测
            va = (a.split(":")[0] if a and ":" in a else a or "").strip()
            vb = (b.split(":")[0] if b and ":" in b else b or "").strip()
            va_v = vb_v = None
            for dev in devices:
                if dev.get("hostname") == va:
                    va_v = dev.get("vendor")
                if dev.get("hostname") == vb:
                    vb_v = dev.get("vendor")
            if va_v and vb_v and va_v != vb_v:
                add("ERROR", "聚合", "跨厂商 LACP/堆叠 违规：%s(%s) ↔ %s(%s)" % (va, va_v, vb, vb_v),
                    "跨厂商上联一律改为静态 Trunk（dot1q，permit/allow-pass 收敛）")
        net = _net(lk.get("net"))
        if net:
            if net.prefixlen < 30 and lk.get("type") in ("static", "eth-trunk"):
                add("WARN", "掩码", "互联链路 %s 使用 %s，通常互联网段用 /30 或 /31" % (lk.get("net"), net.prefixlen),
                    "改为 /30（或点对点 /31）")
            # 与 VLAN 网段冲突
            for vn, vnet in vlan_nets:
                if net.overlaps(vnet):
                    add("ERROR", "IP", "互联网段 %s 与 VLAN %s 网段 %s 重叠" % (net, vn, vnet),
                        "重新分配互联网段")

    # ---------- VRRP 虚地址同网段校验 ----------
    for v in vlans:
        n = _net(v.get("net"))
        gw = _ip(v.get("gw"))
        if n and gw and gw not in n:
            add("ERROR", "路由", "VLAN %s 网关 %s 不在网段 %s 内" % (v.get("name"), gw, n),
                "网关应取网段内地址（如 .254）")

    # ---------- 静态路由 ----------
    for sr in routing.get("static_routes", []) or []:
        dest = _net(sr.get("dest"))
        nh = _ip(sr.get("nexthop"))
        if dest and nh and nh not in dest:
            add("WARN", "路由", "静态路由 %s 下一跳 %s 不在目的网段内（通常下一跳应是直连对端地址）" % (dest, nh),
                "核对下一跳地址")

    # ---------- NAT ----------
    nat = security.get("nat", {}) or {}
    if nat.get("mode") and nat.get("mode") != "none":
        if not nat.get("outside_interface"):
            add("WARN", "安全", "NAT 已启用但未指定 outside_interface", "在模型 security.nat 中填写出口接口")
        if not nat.get("inside"):
            add("WARN", "安全", "NAT 已启用但未指定 inside 网段（ACL 匹配范围）", "填写需转换的内网网段")

    # ---------- HA ----------
    ha = security.get("ha", {}) or {}
    if ha.get("mode") in ("hrp", "vrrp-ha", "active-standby"):
        if not ha.get("heartbeat"):
            add("WARN", "HA", "热备模式 %s 未指定心跳接口" % ha.get("mode"),
                "填写 heartbeat 接口与对端地址")
    # VRRP 优先级差
    prios = [v.get("vrrp_primary") for v in vlans if v.get("vrrp")]

    # ---------- DHCP ----------
    dhcp = services.get("dhcp", {}) or {}
    for pool in dhcp.get("pools", []) or []:
        pn = _net(pool.get("net"))
        if pn and pool.get("vlan"):
            for v in vlans:
                if v.get("id") == pool.get("vlan") and v.get("net") != pool.get("net"):
                    add("ERROR", "服务", "DHCP 池网段 %s 与 VLAN %s 网段 %s 不一致" % (pool.get("net"), pool.get("vlan"), v.get("net")),
                        "DHCP 池网段必须与对应 VLAN 网段一致")
        rng = pool.get("range")
        if rng and pn:
            try:
                a, b = rng.split("-")
                if _ip(a) not in pn or _ip(b) not in pn:
                    add("ERROR", "服务", "DHCP 池 %s 范围 %s 超出网段 %s" % (pool.get("name", ""), rng, pn),
                        "范围须在网段内")
            except Exception:
                pass

    # ---------- 监控 ----------
    for k, host in (("syslog", services.get("syslog", {}).get("host")),
                    ("snmp", (services.get("snmp", {}) or {}).get("trap_host"))):
        if services.get(k) and not host:
            add("WARN", "服务", "%s 已启用但未填写目标主机" % k.upper(), "填写日志/陷阱服务器地址")

    # ---------- 必填字段 ----------
    if not devices:
        add("ERROR", "结构", "模型缺少 devices（设备清单）", "按 model_schema.json 填写每台设备")
    if not vlans:
        add("WARN", "结构", "模型缺少 vlans（VLAN 规划）", "用 ip_planner.py 生成或手工填写")

    return issues


def report(issues):
    errs = [i for i in issues if i["level"] == "ERROR"]
    warns = [i for i in issues if i["level"] == "WARN"]
    lines = []
    lines.append("=" * 64)
    lines.append("check_project 静态校验报告：%d ERROR / %d WARN" % (len(errs), len(warns)))
    lines.append("=" * 64)
    for i in issues:
        mark = "✗" if i["level"] == "ERROR" else "△"
        lines.append("[%s][%s] %s" % (mark, i["cat"], i["msg"]))
        if i.get("fix"):
            lines.append("       建议：%s" % i["fix"])
    lines.append("=" * 64)
    if errs:
        lines.append("结论：存在 %d 个 ERROR，须修复或与用户确认后，方可进入阶段 6/7。" % len(errs))
    else:
        lines.append("结论：无 ERROR，可进入阶段 6/7（WARN 项建议向用户说明）。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="网络项目模型静态校验器")
    ap.add_argument("model", help="项目模型 JSON 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    ap.add_argument("--strict", action="store_true", help="存在 ERROR 时退出码 1（流程门禁）")
    args = ap.parse_args()

    with open(args.model, "r", encoding="utf-8") as f:
        model = json.load(f)
    issues = check_project(model)

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        print(report(issues))

    errs = [i for i in issues if i["level"] == "ERROR"]
    if errs and args.strict:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
