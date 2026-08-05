#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_topo.py —— 网络拓扑图生成器（由 network-deploy 技能阶段 4/6 调用）

功能：
    从项目模型 JSON（model_schema.json 工程化结构）自动生成**美观的拓扑图 PNG**，
    替代抽象 ASCII 线段图。支持：
      - 按角色分层布局：互联网 → 出口路由器 → 防火墙 → 核心 → 汇聚 → 接入 → DMZ/服务器；
      - 角色区分：防火墙=菱形、路由器=圆形、交换机=矩形、服务器=专用符号、互联网=云形；
      - 颜色区分：防火墙红、路由器蓝、核心深蓝、汇聚中蓝、接入浅蓝、DMZ/服务器绿、管理灰；
      - 链路区分：普通链路=实线、聚合/堆叠=粗线、管理链路=虚线；
      - 链路上标注两端接口与网段；
      - 自动图例 + 中文字体支持（Windows 优先 Microsoft YaHei / SimHei）。

用法：
    python gen_topo.py 项目模型.json -o 拓扑图.png
    python gen_topo.py 项目模型.json -o 拓扑图.png --dpi 150
    python gen_topo.py 项目模型.json --list      # 仅列出将绘制的设备/链路
    python gen_topo.py --demo                    # 用内置示例绘制演示拓扑

依赖：
    matplotlib（在隔离虚拟环境中安装，勿污染全局 Python）：
        python -m pip install matplotlib
    若 matplotlib 缺失，脚本会提示安装并退出（不会静默失败）。

输出：PNG（默认 120 dpi，尺寸自适应设备数量）。
"""

import argparse
import json
import math
import os
import sys

try:
    import matplotlib
    matplotlib.use("Agg")  # 无界面后端，支持纯脚本生成
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon, Rectangle, Ellipse
    from matplotlib.lines import Line2D
    from matplotlib import font_manager
except ImportError:
    sys.stderr.write(
        "ERROR: 缺少 matplotlib。请在运行环境的虚拟环境中安装：\n"
        "  python -m pip install matplotlib\n"
    )
    sys.exit(2)

# ---------------- 角色配置：层级 / 形状 / 颜色 ----------------
# 层序（从上到下绘制）；同一层的设备水平排列
LAYER_ORDER = ["internet", "router", "fw", "core", "agg", "access", "server"]

ROLE_CONF = {
    # role: (层级, 图形, 填充色, 描边色, 中文名)
    "internet": (0, "cloud",   "#D9D9D9", "#595959", "互联网"),
    "router":   (1, "circle",  "#B5D4F4", "#185FA5", "出口路由器"),
    "fw":       (2, "diamond", "#F7C1C1", "#A32D2D", "边界防火墙"),
    "core":     (3, "rect",    "#85B7EB", "#185FA5", "核心交换机"),
    "agg":      (4, "rect",    "#B5D4F4", "#185FA5", "汇聚交换机"),
    "access":   (5, "rect",    "#E6F1FB", "#378ADD", "接入交换机"),
    "server":   (6, "server",  "#C0DD97", "#3B6D11", "服务器/DMZ"),
}

# 兼容 role_cn 中可能出现的变体
ROLE_ALIAS = {
    "三层核心": "core", "核心": "core", "core-switch": "core",
    "三层汇聚": "agg", "汇聚": "agg", "汇聚交换机": "agg",
    "二层接入": "access", "接入": "access", "接入交换机": "access",
    "边界防火墙": "fw", "防火墙": "fw", "firewall": "fw",
    "出口设备": "router", "出口路由器": "router", "router": "router",
    "服务器": "server", "服务器区": "server", "dmz": "server", "DMZ": "server",
    "互联网": "internet", "isp": "internet", "ISP": "internet",
}

NODE_W, NODE_H = 3.0, 1.4   # 节点盒尺寸（数据坐标）
LAYER_GAP = 2.0             # 层间距（紧凑布局）
NODE_GAP = 0.8              # 同层节点间距
MARGIN = 2.5                # 画布边距


def normalize_role(dev):
    r = (dev.get("role") or "").strip().lower()
    if r in ROLE_CONF:
        return r
    rc = (dev.get("role_cn") or "").strip()
    return ROLE_ALIAS.get(rc, ROLE_ALIAS.get(r, "access"))


def setup_fonts():
    """配置中文字体：优先 Microsoft YaHei / SimHei，找不到则警告（中文可能显示为方块）。"""
    candidates = ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei"]
    for name in candidates:
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return name
        except Exception:
            continue
    sys.stderr.write("WARN: 未找到中文字体，中文标签可能显示为方块（建议安装微软雅黑）。\n")
    return None


def collect_devices(model):
    """把 devices 映射为 {hostname: dev}，并补入隐含的 internet 节点（若有出口设备）。"""
    devices = {}
    for d in model.get("devices", []):
        hn = d.get("hostname") or "DEV"
        devices[hn] = d
    has_router = any(normalize_role(d) == "router" for d in devices.values())
    if has_router and "Internet" not in devices:
        devices["Internet"] = {"hostname": "Internet", "role": "internet",
                               "role_cn": "互联网", "model": "ISP"}
    return devices


def collect_links(model, devices):
    """标准化 links：返回 [(dev_a, dev_b, 类型, 接口A, 接口B, 网段)]；剔除指向未知设备的链路。"""
    out = []
    for lk in model.get("links", []):
        a = lk.get("a", "")
        b = lk.get("b", "")
        if not a or not b:
            continue
        ha, ia = (a.split(":") + [None])[:2] if ":" in a else (a, None)
        hb, ib = (b.split(":") + [None])[:2] if ":" in b else (b, None)
        if ha not in devices or hb not in devices:
            continue
        if ha == hb:
            continue  # 自环忽略
        ltype = lk.get("type", "static")
        mode = lk.get("mode", "")
        if ltype in ("eth-trunk", "lacp") or mode in ("lacp", "dynamic"):
            k = "agg"
        elif ltype in ("mgmt", "oob") or mode in ("mgmt", "oob"):
            k = "mgmt"
        else:
            k = "normal"
        out.append((ha, hb, k, ia, ib, lk.get("net")))
    return out


def assign_positions(devices):
    """分层布局：每层设备水平排列，返回 {hostname: (x, y)} 与层信息。"""
    layers = {}  # role -> [hostname]
    for hn, dev in devices.items():
        r = normalize_role(dev)
        layers.setdefault(r, []).append(hn)
    # 按层序放置；同层内先按名称排序，保证 DSW1/DSW2 相邻
    pos = {}
    y_top = 0.0
    layer_y = {}
    for r in LAYER_ORDER:
        members = layers.get(r, [])
        if not members:
            continue
        members_sorted = sorted(members, key=lambda h: (len(h), h))
        total_w = len(members_sorted) * (NODE_W + NODE_GAP) - NODE_GAP
        x_start = -total_w / 2
        layer_y[r] = y_top
        for i, hn in enumerate(members_sorted):
            x = x_start + i * (NODE_W + NODE_GAP) + NODE_W / 2
            pos[hn] = (x, y_top)
        y_top -= LAYER_GAP
    return pos, layer_y


def draw_device(ax, x, y, role, label, sublabel, size=(NODE_W, NODE_H)):
    w, h = size
    fill, edge = ROLE_CONF[role][2], ROLE_CONF[role][3]
    if role == "cloud":
        # 云形：用两个椭圆组合的简化云
        e1 = Ellipse((x - 0.9, y - 0.15), 1.8, 1.3, fc=fill, ec=edge, lw=1.5)
        e2 = Ellipse((x + 0.9, y - 0.15), 1.8, 1.3, fc=fill, ec=edge, lw=1.5)
        e3 = Ellipse((x, y + 0.35), 2.4, 1.5, fc=fill, ec=edge, lw=1.5)
        for e in (e1, e2, e3):
            ax.add_patch(e)
    elif role == "diamond":
        dia = Polygon([(x, y + h / 2), (x + w * 0.62, y), (x, y - h / 2), (x - w * 0.62, y)],
                      closed=True, fc=fill, ec=edge, lw=1.5, zorder=3)
        ax.add_patch(dia)
    elif role == "circle":
        c = Circle((x, y), radius=min(w, h) / 1.7, fc=fill, ec=edge, lw=1.5, zorder=3)
        ax.add_patch(c)
    elif role == "server":
        # 服务器：矩形 + 内部分隔线（1U 机架样式）
        r = Rectangle((x - w / 2, y - h / 2), w, h, fc=fill, ec=edge, lw=1.5, zorder=3)
        ax.add_patch(r)
        for i in range(1, 3):
            ax.plot([x - w / 2 + 0.25, x + w / 2 - 0.25], [y - h / 2 + i * h / 3] * 2,
                    color=edge, lw=0.8, zorder=4)
    else:  # rect（交换机）
        r = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                           boxstyle="round,pad=0.08", fc=fill, ec=edge, lw=1.5, zorder=3)
        ax.add_patch(r)
    # 主标签（hostname）
    ax.text(x, y + h * 0.12, label, ha="center", va="center",
            fontsize=10, fontweight="bold", zorder=5)
    # 副标签（型号/角色）
    ax.text(x, y - h * 0.28, sublabel, ha="center", va="center",
            fontsize=7.5, color="#444444", zorder=5)


def draw_link(ax, p1, p2, kind, iface_a, iface_b, net):
    (x1, y1), (x2, y2) = p1, p2
    if kind == "agg":
        color, lw, ls = "#0F6E56", 3.2, "-"
    elif kind == "mgmt":
        color, lw, ls = "#888888", 1.4, "--"
    else:
        color, lw, ls = "#404040", 1.8, "-"
    ax.plot([x1, x2], [y1, y2], color=color, lw=lw, ls=ls, zorder=1)
    # 中点标注网段/接口
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    label_parts = []
    if iface_a or iface_b:
        label_parts.append("%s <-> %s" % (iface_a or "-", iface_b or "-"))
    if net:
        label_parts.append(net)
    if label_parts:
        ax.text(mx, my + 0.35, "  ".join(label_parts), ha="center", va="bottom",
                fontsize=6.5, color="#555555",
                bbox=dict(fc="white", ec="none", alpha=0.75, pad=0.5), zorder=6)


def draw_legend(ax):
    handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=ROLE_CONF["router"][2],
               markeredgecolor=ROLE_CONF["router"][3], markersize=9, label="出口路由器"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor=ROLE_CONF["fw"][2],
               markeredgecolor=ROLE_CONF["fw"][3], markersize=8, label="边界防火墙"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor=ROLE_CONF["core"][2],
               markeredgecolor=ROLE_CONF["core"][3], markersize=8, label="交换机"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor=ROLE_CONF["server"][2],
               markeredgecolor=ROLE_CONF["server"][3], markersize=8, label="服务器/DMZ"),
        Line2D([0], [0], color="#404040", lw=1.8, label="普通链路"),
        Line2D([0], [0], color="#0F6E56", lw=3.0, label="聚合/堆叠"),
        Line2D([0], [0], color="#888888", lw=1.4, ls="--", label="管理链路"),
    ]
    leg = ax.legend(handles=handles, loc="lower left", fontsize=7.5, framealpha=0.9,
                    bbox_to_anchor=(0.0, 0.0), ncol=2)
    leg.get_frame().set_edgecolor("#BBBBBB")


def build(model, out_path, dpi=120, title=None):
    font_name = setup_fonts()
    devices = collect_devices(model)
    links = collect_links(model, devices)
    pos, layer_y = assign_positions(devices)

    n_layers = len(layer_y)
    height = max(10, n_layers * LAYER_GAP + MARGIN * 2)
    # 画布宽度按层内最大设备数计算（不是全部设备总和），避免过宽
    max_per_layer = max((len([h for h in devices if normalize_role(devices[h]) == r]) for r in LAYER_ORDER), default=1)
    width = max(12, max_per_layer * (NODE_W + NODE_GAP) + MARGIN * 2 + 2)

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    ax.set_xlim(-width / 2, width / 2)
    ax.set_ylim(-height / 2 - 1.5, height / 2)
    ax.axis("off")

    # 标题
    proj = (model.get("meta") or {}).get("project_name", "网络项目")
    ax.set_title(title or ("%s —— 网络拓扑图" % proj), fontsize=14, fontweight="bold", pad=18)

    # 画链路（先画线，再画节点盖在上面，层次更干净）
    for (ha, hb, kind, ia, ib, net) in links:
        if ha in pos and hb in pos:
            draw_link(ax, pos[ha], pos[hb], kind, ia, ib, net)

    # 画节点
    for hn, dev in devices.items():
        if hn not in pos:
            continue
        x, y = pos[hn]
        role = normalize_role(dev)
        model_name = dev.get("model") or ""
        role_cn = ROLE_CONF[role][4]
        sub = f"{role_cn}{(' · ' + str(model_name)) if model_name else ''}"
        draw_device(ax, x, y, role, hn, sub)

    draw_legend(ax)

    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("OK: 已生成拓扑图 -> %s (%dx%d px)" % (out_path, int(width * dpi), int(height * dpi)))
    if font_name:
        print("INFO: 使用中文字体 %s" % font_name)


def main():
    ap = argparse.ArgumentParser(description="网络拓扑图生成器（模型 → 拓扑 PNG）")
    ap.add_argument("model", nargs="?", help="项目模型 JSON 路径")
    ap.add_argument("-o", "--out", default="拓扑图.png", help="输出 PNG 路径（默认 拓扑图.png）")
    ap.add_argument("--dpi", type=int, default=120, help="图片分辨率（默认 120）")
    ap.add_argument("--title", default=None, help="自定义标题（默认取项目名）")
    ap.add_argument("--list", action="store_true", help="仅列出将绘制的设备/链路")
    ap.add_argument("--demo", action="store_true", help="用内置示例绘制演示拓扑")
    args = ap.parse_args()

    if args.demo or not args.model:
        demo = {
            "meta": {"project_name": "演示园区网"},
            "devices": [
                {"hostname": "AR1", "role": "router", "role_cn": "出口设备", "model": "华三 MSR"},
                {"hostname": "AR2", "role": "router", "role_cn": "出口设备", "model": "华三 MSR"},
                {"hostname": "FW1", "role": "fw", "role_cn": "边界防火墙", "model": "华为 USG6000"},
                {"hostname": "FW2", "role": "fw", "role_cn": "边界防火墙", "model": "华为 USG6000"},
                {"hostname": "DSW1", "role": "core", "role_cn": "三层核心", "model": "华为 S5735"},
                {"hostname": "DSW2", "role": "core", "role_cn": "三层核心", "model": "华为 S5735"},
                {"hostname": "ASW1", "role": "access", "role_cn": "二层接入", "model": "思科 C2960"},
                {"hostname": "ASW2", "role": "access", "role_cn": "二层接入", "model": "思科 C2960"},
                {"hostname": "WEB1", "role": "server", "role_cn": "DMZ服务器", "model": "Web"},
            ],
            "links": [
                {"a": "Internet:GE0/0/0", "b": "AR1:GE0/0/0", "type": "static"},
                {"a": "Internet:GE0/0/0", "b": "AR2:GE0/0/0", "type": "static"},
                {"a": "AR1:GE0/0/1", "b": "FW1:GE1/0/0", "type": "static"},
                {"a": "AR2:GE0/0/1", "b": "FW2:GE1/0/0", "type": "static"},
                {"a": "AR1:GE0/0/2", "b": "FW2:GE1/0/3", "type": "static"},
                {"a": "FW1:GE1/0/1", "b": "DSW1:GE0/0/1", "type": "static"},
                {"a": "FW2:GE1/0/1", "b": "DSW2:GE0/0/1", "type": "static"},
                {"a": "DSW1:GE0/0/24", "b": "DSW2:GE0/0/24", "type": "eth-trunk", "id": 1},
                {"a": "DSW1:GE0/0/2", "b": "ASW1:GE0/0/24", "type": "static"},
                {"a": "DSW2:GE0/0/2", "b": "ASW1:GE0/0/23", "type": "static"},
                {"a": "DSW1:GE0/0/3", "b": "ASW2:GE0/0/24", "type": "static"},
                {"a": "DSW2:GE0/0/3", "b": "ASW2:GE0/0/23", "type": "static"},
                {"a": "FW1:GE1/0/2", "b": "WEB1:eth0", "type": "static"},
            ],
        }
        model = demo
    else:
        with open(args.model, "r", encoding="utf-8") as f:
            model = json.load(f)

    devices = collect_devices(model)
    links = collect_links(model, devices)

    if args.list:
        print("== 设备 ==")
        for hn, dev in devices.items():
            print("  %-12s %s" % (hn, ROLE_CONF[normalize_role(dev)][4]))
        print("== 链路 ==")
        for ha, hb, k, ia, ib, net in links:
            print("  %s ↔ %s  [%s]" % (ha, hb, k))
        return

    build(model, args.out, dpi=args.dpi, title=args.title)


if __name__ == "__main__":
    main()
