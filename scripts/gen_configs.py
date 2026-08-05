#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_configs.py —— 逐设备配置文件生成器（由 network-deploy 技能阶段 7 调用）

功能：
    从升级后的项目模型（model_schema.json 工程化结构：devices/vlans/links/
    routing/security/services）为每台设备生成"可执行配置骨架"，注释符天然按厂商
    正确分派（思科 `!`、华为/华三 `#`），并自动追加保存命令（思科 write memory、
    华为/华三 save），按 `主机名_角色_v1.txt` 命名。

    生成的是"骨架"：覆盖基础/管理/VLAN/接口/路由/策略等通用块；需要 AI 根据
    用户确认的特殊策略（QoS、PBR、802.1x RADIUS 细节等）补全差异化部分，
    并对记忆外/新机型命令做 Web 查证。生成后建议统一跑 normalize_comments.py 兜底。

用法：
    python gen_configs.py 项目模型.json --outdir ./配置
    python gen_configs.py 项目模型.json --outdir ./配置 --dry-run   # 仅打印不写盘
    python gen_configs.py 项目模型.json --list                      # 列出将生成的设备

输出：
    配置/<主机名>_<角色>_v1.txt

模型字段约定（详见 references/model_schema.json）：
    devices[].{hostname,vendor,model,role,role_cn,mgmt_ip,mgmt_vlan,loopback,
               interfaces:[{name,peer,mode,vlan,allowed_vlans,ip,desc}]}
    vlans[]        {id,name,net,gw,vrrp,vrrp_vrid,vrrp_primary}
    links[]        {a,b,type,id,mode,vlan_mode,allowed_vlans,net}
    routing        {protocol,process,router_id_source,areas,default_route,static_routes}
    security       {acls,nat,zones,ha}
    services       {dhcp,aaa,snmp,syslog,ntp,bfd}

注释符风格（重要）：
    输出遵循厂商官方风格：命令逐行书写，段落之间用独立一行的注释/分隔符
    （思科 `!`、华为/华三 `#`）隔开。命令行本身不带注释符前缀，否则会被设备
    当作注释忽略，导致配置失效。
"""

import argparse
import ipaddress
import json
import os
import sys

VENDOR_COMMENT = {"cisco": "!", "huawei": "#", "h3c": "#"}
ROLE_CN = {
    "core": "三层核心", "agg": "三层汇聚", "access": "二层接入",
    "fw": "边界防火墙", "router": "出口设备", "server": "服务器",
}


class CfgBuilder:
    """按厂商风格收集配置行：cmd() 写命令，sep() 写独立分隔行"""

    def __init__(self, comment):
        self.comment = comment
        self.lines = []

    def cmd(self, text):
        if text:
            self.lines.append(text)

    def sep(self):
        self.lines.append(self.comment)

    def block(self, *cmds):
        for c in cmds:
            if c:
                self.lines.append(c)
        self.lines.append(self.comment)

    def text(self):
        return "\n".join(self.lines) + "\n"


# ------------------------- 思科 IOS / IOS-XE -------------------------

def gen_cisco(dev, model):
    C = "!"
    b = CfgBuilder(C)
    h = dev.get("hostname", "SW")
    is_l3 = dev.get("role") in ("core", "agg", "router", "fw") or dev.get("loopback")
    b.block("hostname %s" % h)
    b.block("enable secret %s" % _secret(model))
    b.block("username admin privilege 15 secret %s" % _secret(model))
    b.block("line vty 0 4", " login local", " transport input ssh")
    b.block("service password-encryption",
            "ip domain-name lab.local",
            "crypto key generate rsa modulus 2048",
            "ip ssh version 2")

    mgmt_vlan = dev.get("mgmt_vlan")
    mgmt_ip = dev.get("mgmt_ip")
    if mgmt_vlan and mgmt_ip:
        b.block("vlan %s" % mgmt_vlan,
                " name MGMT")
        b.block("interface Vlan%s" % mgmt_vlan,
                " ip address %s %s" % (_addr(mgmt_ip), _mask(mgmt_ip)),
                " no shutdown")

    vlan_ids = [v["id"] for v in model.get("vlans", []) if v.get("id")]
    if vlan_ids:
        b.block("vlan %s" % ",".join(str(i) for i in vlan_ids))

    for itf in dev.get("interfaces", []):
        iname = itf.get("name", "")
        mode = itf.get("mode")
        cmds = ["interface %s" % iname]
        if itf.get("desc"):
            cmds.append(" description %s" % itf["desc"])
        if mode == "access":
            cmds.append(" switchport mode access")
            if itf.get("vlan"):
                cmds.append(" switchport access vlan %s" % itf["vlan"])
            cmds.append(" spanning-tree portfast")
        elif mode == "trunk":
            cmds.append(" switchport trunk encapsulation dot1q")
            cmds.append(" switchport mode trunk")
            if itf.get("allowed_vlans"):
                cmds.append(" switchport trunk allowed vlan %s" % ",".join(str(v) for v in itf["allowed_vlans"]))
        if itf.get("ip"):
            cmds.append(" ip address %s %s" % (_addr(itf["ip"]), _mask(itf["ip"])))
            cmds.append(" no shutdown")
        b.block(*cmds)

    # VRRP 仅在具备三层能力的设备上生成（接入层不做网关）
    if is_l3:
        for v in model.get("vlans", []):
            if v.get("vrrp") and v.get("gw") and v.get("id"):
                vid = v["id"]
                is_primary = v.get("vrrp_primary") == h
                prio = 120 if is_primary else 100
                vr = v.get("vrrp_vrid") or vid
                b.block("interface Vlan%s" % vid,
                        " ip address %s %s" % (_addr(v["gw"]), _mask(v["net"])),
                        " vrrp %s ip %s" % (vr, v["gw"]),
                        " vrrp %s priority %s" % (vr, prio))

    if is_l3:
        if dev.get("loopback"):
            b.block("interface Loopback0",
                    " ip address %s 255.255.255.255" % dev["loopback"])
        prot = model.get("routing", {}).get("protocol")
        if prot == "ospf":
            proc = model.get("routing", {}).get("process", 1)
            cmds = ["router ospf %s" % proc,
                    " router-id %s" % (dev.get("loopback") or "1.1.1.1")]
            for area, nets in (model.get("routing", {}).get("areas") or {}).items():
                for n in nets:
                    cmds.append(" network %s %s area %s" % (_addr(n), _wildcard(n), area))
            b.block(*cmds)
        for sr in (model.get("routing", {}).get("static_routes") or []):
            b.block("ip route %s %s %s" % (sr.get("dest"), _mask(sr.get("dest")), sr.get("nexthop")))

    nat = model.get("security", {}).get("nat", {}) or {}
    if nat.get("mode") and nat.get("mode") != "none" and dev.get("role") in ("router", "fw"):
        inside = (nat.get("inside") or ["10.0.0.0/8"])[0]
        b.block("interface GigabitEthernet0/0",
                " ip nat inside")
        b.block("interface GigabitEthernet0/1",
                " ip nat outside")
        b.block("access-list 1 permit %s" % inside,
                "ip nat inside source list 1 interface GigabitEthernet0/1 overload")
    # ACL：仅三层设备生成；思科用标准 access-list 语法（模型 rules 为华为风格时需 AI 转换）
    if is_l3:
        for acl in (model.get("security", {}).get("acls") or []):
            for r in acl.get("rules", []):
                if acl.get("id") == 2000:
                    continue  # NAT ACL 已由 nat 块生成
                b.cmd("access-list %s %s" % (acl.get("id"), r))
            if acl.get("rules"):
                b.sep()

    svc = model.get("services", {}) or {}
    if svc.get("snmp"):
        snmp = svc["snmp"]
        cmds = ["snmp-server community %s RO" % snmp.get("community", "public")]
        if snmp.get("trap_host"):
            cmds.append("snmp-server host %s version 2c %s" % (snmp["trap_host"], snmp.get("community", "public")))
        b.block(*cmds)
    if svc.get("syslog", {}).get("host"):
        b.block("logging host %s" % svc["syslog"]["host"],
                "logging trap informational")
    if svc.get("ntp", {}).get("server"):
        b.block("ntp server %s" % svc["ntp"]["server"])
    if svc.get("bfd") and is_l3:
        bfd = svc["bfd"]
        b.block("interface GigabitEthernet0/1",
                " bfd interval %s min_rx %s multiplier %s" % (
                    bfd.get("interval_ms", 100), bfd.get("interval_ms", 100), bfd.get("multiplier", 3)))

    b.block("write memory")
    return b.text()


# ------------------------- 华为 VRP -------------------------

def gen_huawei(dev, model):
    C = "#"
    b = CfgBuilder(C)
    h = dev.get("hostname", "SW")
    is_l3 = dev.get("role") in ("core", "agg", "router", "fw") or dev.get("loopback")
    b.block("sysname %s" % h)
    b.block("aaa",
            " local-user admin password cipher %s" % _secret(model),
            " local-user admin service-type terminal ssh http",
            " local-user admin privilege level 15")
    b.block("user-interface vty 0 4",
            " authentication-mode aaa",
            " protocol inbound ssh")
    b.block("stelnet server enable")

    mgmt_vlan = dev.get("mgmt_vlan")
    mgmt_ip = dev.get("mgmt_ip")
    if mgmt_vlan and mgmt_ip:
        b.block("interface Vlanif%s" % mgmt_vlan,
                " ip address %s %s" % (_addr(mgmt_ip), _mask(mgmt_ip)))

    vlan_ids = [v["id"] for v in model.get("vlans", []) if v.get("id")]
    if vlan_ids:
        b.block("vlan batch %s" % " ".join(str(i) for i in vlan_ids))

    for itf in dev.get("interfaces", []):
        iname = itf.get("name", "")
        mode = itf.get("mode")
        cmds = ["interface %s" % iname]
        if itf.get("desc"):
            cmds.append(" description %s" % itf["desc"])
        if mode == "access":
            cmds.append(" port link-type access")
            if itf.get("vlan"):
                cmds.append(" port default vlan %s" % itf["vlan"])
            cmds.append(" stp edged-port enable")
        elif mode == "trunk":
            cmds.append(" port link-type trunk")
            if itf.get("allowed_vlans"):
                cmds.append(" port trunk allow-pass vlan %s" % " ".join(str(v) for v in itf["allowed_vlans"]))
        if itf.get("ip"):
            cmds.append(" ip address %s" % itf["ip"])
        b.block(*cmds)

    # VRRP 仅在三层设备上生成
    if is_l3:
        for v in model.get("vlans", []):
            if v.get("vrrp") and v.get("gw") and v.get("id"):
                vid = v["id"]
                is_primary = v.get("vrrp_primary") == h
                prio = 120 if is_primary else 100
                vr = v.get("vrrp_vrid") or vid
                b.block("interface Vlanif%s" % vid,
                        " ip address %s %s" % (_addr(v["gw"]), _mask(v["net"])),
                        " vrrp vrid %s virtual-ip %s" % (vr, v["gw"]),
                        " vrrp vrid %s priority %s" % (vr, prio))

    if is_l3:
        if dev.get("loopback"):
            b.block("interface LoopBack0",
                    " ip address %s 255.255.255.255" % dev["loopback"])
        prot = model.get("routing", {}).get("protocol")
        if prot == "ospf":
            proc = model.get("routing", {}).get("process", 1)
            rid = dev.get("loopback") or "1.1.1.1"
            cmds = ["ospf %s router-id %s" % (proc, rid)]
            for area, nets in (model.get("routing", {}).get("areas") or {}).items():
                cmds.append(" area %s" % area)
                for n in nets:
                    cmds.append("  network %s" % n)
            b.block(*cmds)
        for sr in (model.get("routing", {}).get("static_routes") or []):
            b.block("ip route-static %s %s" % (sr.get("dest"), sr.get("nexthop")))

    nat = model.get("security", {}).get("nat", {}) or {}
    if dev.get("role") == "fw":
        zones = (model.get("security", {}).get("zones") or {})
        for zn, itfs in zones.items():
            cmds = ["firewall zone %s" % zn]
            for itf in itfs:
                cmds.append(" add interface %s" % itf)
            b.block(*cmds)
        ha = (model.get("security", {}).get("ha") or {})
        if ha.get("mode") == "hrp":
            cmds = ["hrp enable"]
            if ha.get("heartbeat"):
                cmds.append("hrp interface %s" % ha["heartbeat"])
            if ha.get("priority"):
                cmds.append("hrp priority %s" % ha["priority"])
            b.block(*cmds)
    elif nat.get("mode") and nat.get("mode") != "none":
        for acl in (model.get("security", {}).get("acls") or []):
            if acl.get("id") == 2000:
                cmds = ["acl number 2000"]
                for r in acl.get("rules", []):
                    cmds.append(" %s" % r)
                b.block(*cmds)
        b.block("interface GigabitEthernet0/0/1",
                " nat outbound 2000")
    for acl in (model.get("security", {}).get("acls") or []):
        if dev.get("role") != "fw" and acl.get("id") != 2000:
            cmds = ["acl number %s" % acl.get("id")]
            for r in acl.get("rules", []):
                cmds.append(" %s" % r)
            b.block(*cmds)

    svc = model.get("services", {}) or {}
    if svc.get("snmp"):
        snmp = svc["snmp"]
        cmds = ["snmp-agent",
                "snmp-agent community read %s" % snmp.get("community", "public")]
        if snmp.get("trap_host"):
            cmds.append("snmp-agent target-host trap address udp-domain %s params securityname %s" % (
                snmp["trap_host"], snmp.get("community", "public")))
        b.block(*cmds)
    if svc.get("syslog", {}).get("host"):
        b.block("info-center loghost %s" % svc["syslog"]["host"])
    if svc.get("ntp", {}).get("server"):
        b.block("ntp-service unicast-server %s" % svc["ntp"]["server"])
    if svc.get("bfd") and is_l3:
        bfd = svc["bfd"]
        b.block("bfd")
        b.block("interface GigabitEthernet0/0/1",
                " bfd min-transmit-interval %s" % bfd.get("interval_ms", 100),
                " bfd min-receive-interval %s" % bfd.get("interval_ms", 100),
                " bfd detect-multiplier %s" % bfd.get("multiplier", 3))

    b.block("save")
    return b.text()


# ------------------------- 华三 Comware -------------------------

def gen_h3c(dev, model):
    C = "#"
    b = CfgBuilder(C)
    h = dev.get("hostname", "SW")
    is_l3 = dev.get("role") in ("core", "agg", "router", "fw") or dev.get("loopback")
    b.block("sysname %s" % h)
    b.block("local-user admin class manage",
            " password simple %s" % _secret(model),
            " service-type ssh terminal",
            " authorization-attribute user-role network-admin")
    b.block("user-interface vty 0 4",
            " authentication-mode scheme",
            " protocol inbound ssh")
    b.block("ssh server enable")

    mgmt_vlan = dev.get("mgmt_vlan")
    mgmt_ip = dev.get("mgmt_ip")
    if mgmt_vlan and mgmt_ip:
        b.block("vlan %s" % mgmt_vlan)
        b.block("interface Vlan-interface%s" % mgmt_vlan,
                " ip address %s %s" % (_addr(mgmt_ip), _mask(mgmt_ip)))

    vlan_ids = [v["id"] for v in model.get("vlans", []) if v.get("id")]
    for vid in vlan_ids:
        b.block("vlan %s" % vid)

    for itf in dev.get("interfaces", []):
        iname = itf.get("name", "")
        mode = itf.get("mode")
        cmds = ["interface %s" % iname,
                " port link-mode bridge"]
        if itf.get("desc"):
            cmds.append(" description %s" % itf["desc"])
        if mode == "access":
            if itf.get("vlan"):
                cmds.append(" port access vlan %s" % itf["vlan"])
            cmds.append(" stp edged-port")
        elif mode == "trunk":
            cmds.append(" port link-type trunk")
            if itf.get("allowed_vlans"):
                cmds.append(" port trunk permit vlan %s" % " ".join(str(v) for v in itf["allowed_vlans"]))
        if itf.get("ip"):
            cmds.append(" ip address %s %s" % (_addr(itf["ip"]), _mask(itf["ip"])))
        b.block(*cmds)

    # VRRP 仅在三层设备上生成
    if is_l3:
        for v in model.get("vlans", []):
            if v.get("vrrp") and v.get("gw") and v.get("id"):
                vid = v["id"]
                is_primary = v.get("vrrp_primary") == h
                prio = 120 if is_primary else 100
                vr = v.get("vrrp_vrid") or vid
                b.block("interface Vlan-interface%s" % vid,
                        " ip address %s %s" % (_addr(v["gw"]), _mask(v["net"])),
                        " vrrp vrid %s virtual-ip %s" % (vr, v["gw"]),
                        " vrrp vrid %s priority %s" % (vr, prio))

    if is_l3:
        if dev.get("loopback"):
            b.block("interface LoopBack0",
                    " ip address %s 255.255.255.255" % dev["loopback"])
        prot = model.get("routing", {}).get("protocol")
        if prot == "ospf":
            proc = model.get("routing", {}).get("process", 1)
            cmds = ["ospf %s router-id %s" % (proc, dev.get("loopback") or "1.1.1.1")]
            for area, nets in (model.get("routing", {}).get("areas") or {}).items():
                cmds.append(" area %s" % area)
                for n in nets:
                    cmds.append("  network %s" % n)
            b.block(*cmds)
        for sr in (model.get("routing", {}).get("static_routes") or []):
            b.block("ip route-static %s %s" % (sr.get("dest"), sr.get("nexthop")))

    nat = model.get("security", {}).get("nat", {}) or {}
    if nat.get("mode") and nat.get("mode") != "none" and dev.get("role") == "router":
        cmds = ["acl basic 2000"]
        for acl in (model.get("security", {}).get("acls") or []):
            if acl.get("id") == 2000:
                for r in acl.get("rules", []):
                    cmds.append(" %s" % r)
        b.block(*cmds)
        b.block("interface GigabitEthernet0/0/1",
                " nat outbound 2000")

    svc = model.get("services", {}) or {}
    if svc.get("snmp"):
        snmp = svc["snmp"]
        cmds = ["snmp-agent",
                "snmp-agent community read %s" % snmp.get("community", "public")]
        if snmp.get("trap_host"):
            cmds.append("snmp-agent target-host trap address udp-domain %s params securityname %s" % (
                snmp["trap_host"], snmp.get("community", "public")))
        b.block(*cmds)
    if svc.get("syslog", {}).get("host"):
        b.block("info-center loghost %s" % svc["syslog"]["host"])
    if svc.get("ntp", {}).get("server"):
        b.block("ntp-service unicast-server %s" % svc["ntp"]["server"])

    b.block("save")
    return b.text()


GENERATORS = {
    "cisco": gen_cisco,
    "huawei": gen_huawei,
    "h3c": gen_h3c,
}


def _addr(net_or_ip):
    """把 '10.10.0.21/24' → '10.10.0.21'；'10.10.0.0/16' → '10.10.0.0'（网络地址）"""
    try:
        return str(ipaddress.ip_interface(str(net_or_ip)).ip)
    except Exception:
        pass
    try:
        n = ipaddress.ip_network(str(net_or_ip), strict=False)
        return str(n.network_address)
    except Exception:
        return str(net_or_ip)


def _mask(net_or_ip):
    try:
        return str(ipaddress.ip_interface(str(net_or_ip)).netmask)
    except Exception:
        try:
            return str(ipaddress.ip_network(str(net_or_ip), strict=False).netmask)
        except Exception:
            return "255.255.255.0"


def _wildcard(net):
    try:
        n = ipaddress.ip_network(str(net), strict=False)
        return str(n.hostmask)
    except Exception:
        return "0.255.255.255"


def _secret(model):
    creds = model.get("meta", {}).get("credentials", {})
    return creds.get("enable", creds.get("admin", "Str0ng@Pass123"))


def build_all(model):
    out_files = []
    for dev in model.get("devices", []):
        vendor = (dev.get("vendor") or "").lower()
        if vendor == "h3c":
            gen = gen_h3c
        elif vendor == "huawei":
            gen = gen_huawei
        elif vendor in ("cisco", "ios", "ios-xe"):
            gen = gen_cisco
        else:
            sys.stderr.write(
                "WARN: 设备 %s 厂商 %s 不在内置模板（cisco/huawei/h3c）中。\n"
                "     按 SKILL.md『CLI 命令来源与查证』三方交叉验证：AI 记忆 + 网络搜索同时参考，\n"
                "     冲突时查 cmds.md 三方对比、以网络结果为准（网络不可用时以 AI 记忆为准并告知用户），\n"
                "     再写入 %s_%s_v1.txt。\n"
                % (dev.get("hostname"), vendor, dev.get("hostname", "DEV"), ROLE_CN.get(dev.get("role", ""), "设备"))
            )
            continue
        content = gen(dev, model)
        role_cn = dev.get("role_cn") or ROLE_CN.get(dev.get("role", ""), "设备")
        fname = "%s_%s_v1.txt" % (dev.get("hostname", "DEV"), role_cn)
        out_files.append((fname, content))
    return out_files


def main():
    ap = argparse.ArgumentParser(description="逐设备配置文件生成器（模型 → 配置骨架）")
    ap.add_argument("model", help="项目模型 JSON 路径")
    ap.add_argument("--outdir", default="配置", help="输出目录（默认 ./配置）")
    ap.add_argument("--dry-run", action="store_true", help="仅打印不写盘")
    ap.add_argument("--list", action="store_true", help="仅列出将生成的设备")
    args = ap.parse_args()

    with open(args.model, "r", encoding="utf-8") as f:
        model = json.load(f)

    files = build_all(model)
    if args.list:
        for fname, _ in files:
            print(fname)
        return

    if args.dry_run:
        for fname, content in files:
            print("=" * 60)
            print(fname)
            print("=" * 60)
            print(content)
        return

    os.makedirs(args.outdir, exist_ok=True)
    for fname, content in files:
        path = os.path.join(args.outdir, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("已生成 -> %s" % path)
    print("共生成 %d 个配置文件" % len(files))


if __name__ == "__main__":
    main()
