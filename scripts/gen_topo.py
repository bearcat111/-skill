#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_topo.py —— 网络拓扑图生成器（由 network-deploy 技能阶段 4/6 调用）

功能：
    从项目模型 JSON（model_schema.json 工程化结构）自动生成**科研制图质量的可视化
    拓扑图 PNG**，替代抽象 ASCII 线段图。支持：
      - 按角色分层布局：互联网 → 出口路由器 → 防火墙 → 核心 → 汇聚 → 接入 → DMZ/服务器；
      - **按设备类型分类形状**：
          路由器        → 椭圆形
          二层交换机    → 正方形
          三层交换机    → 横长方形（长:宽 ≈ 1:0.618 黄金比例）
          服务器/DMZ    → 竖长方形（长:宽 ≈ 0.618:1）
          防火墙        → 正方形
          互联网        → 云形
          其余设备      → 正方形
      - **同类型同色、浅色调随机**：每种设备类型随机生成一个浅色（低饱和/高亮度，
        不抢眼、不影响文字阅读）；路由器与路由器同色、二层与二层同色……；
      - 链路区分：普通链路=实线、聚合/堆叠=粗线、管理链路=虚线；
      - 链路上标注两端接口与网段；
      - **弹性画布**：图片长宽由拓扑实际边界 + 留白决定（小型拓扑不产生大量空白），
        密度一致，接近科研制图；
      - 自动图例 + 中文字体支持（Windows 优先 Microsoft YaHei / SimHei）。

用法：
    python gen_topo.py 项目模型.json -o 拓扑图.png
    python gen_topo.py 项目模型.json -o 拓扑图.png --dpi 150
    python gen_topo.py 项目模型.json -o 拓扑图.png --seed 42   # 固定配色（可复现）
    python gen_topo.py 项目模型.json --list      # 仅列出将绘制的设备/链路
    python gen_topo.py --demo                    # 用内置示例绘制演示拓扑（固定配色）

依赖：
    matplotlib（在隔离虚拟环境中安装，勿污染全局 Python）：
        python -m pip install matplotlib
    若 matplotlib 缺失，脚本会提示安装并退出（不会静默失败）。
"""

import argparse
import colorsys
import json
import math
import os
import random
import sys

try:
    import matplotlib
    matplotlib.use("Agg")  # 无界面后端，支持纯脚本生成
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle, Ellipse
    from matplotlib.lines import Line2D
    from matplotlib import font_manager
except ImportError:
    sys.stderr.write(
        "ERROR: 缺少 matplotlib。请在运行环境的虚拟环境中安装：\n"
        "  python -m pip install matplotlib\n"
    )
    sys.exit(2)

# ---------------- 角色与形状配置 ----------------
# 层序（从上到下绘制）；同一层的设备水平排列
LAYER_ORDER = ["internet", "router", "fw", "core", "agg", "access", "server"]

# role -> 形状类别（决定图形与宽高比）
ROLE_SHAPE = {
    "internet": "cloud",    # 云形
    "router":   "ellipse",  # 椭圆形
    "fw":       "square",   # 正方形（防火墙）
    "core":     "l3",       # 三层交换机：横黄金矩形
    "agg":      "l3",       # 三层交换机：横黄金矩形
    "access":   "l2",       # 二层交换机：正方形
    "server":   "vrect",    # 服务器：竖黄金矩形
}

# 形状 -> 中文名
SHAPE_CN = {
    "cloud":   "互联网",
    "ellipse": "出口路由器",
    "square":  "防火墙/设备",
    "l3":      "三层交换机",
    "l2":      "二层交换机",
    "vrect":   "服务器/DMZ",
}

# 形状 -> (宽度, 高度) 数据单位
# 长:宽 = 1:0.618 → w/h = 1.618（三层交换机横置）
# 长:宽 = 0.618:1 → w/h = 0.618（服务器竖置）
GOLD = 1.618
BASE = 2.2
SHAPE_SIZE = {
    "cloud":   (BASE * 1.7, BASE),          # 互联网云形（较宽）
    "ellipse": (BASE * 1.5, BASE * 0.95),   # 路由器椭圆包络
    "square":  (BASE, BASE),                # 正方形（二层/防火墙/其他）
    "l3":      (BASE * GOLD, BASE),         # 横黄金矩形
    "l2":      (BASE, BASE),                # 二层 = 正方形
    "vrect":   (BASE / GOLD, BASE),         # 竖黄金矩形
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

LAYER_GAP = 3.0     # 层间距（数据单位，原 2.0 放大 50%）
NODE_GAP = 1.8      # 同层节点间距（原 1.2 放大 50%）
PAD = 2.2           # 画布四周留白（数据单位，原 1.6 放大）
UNITS_PER_INCH = 2.0  # 每英寸对应的数据单位数（决定节点在成图中的物理大小）


def normalize_role(dev):
    r = (dev.get("role") or "").strip().lower()
    if r in ROLE_SHAPE:
        return r
    rc = (dev.get("role_cn") or "").strip()
    return ROLE_ALIAS.get(rc, ROLE_ALIAS.get(r, "access"))


def shape_of(role):
    return ROLE_SHAPE.get(role, "square")


def size_of(role):
    return SHAPE_SIZE[shape_of(role)]


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


def pastel_color(rng):
    """生成一个浅色（HSL 低饱和、高亮度）+ 配套深描边色。返回 (fill_hex, edge_hex)。"""
    h = rng.random()
    s = rng.uniform(0.22, 0.40)   # 低饱和 → 不抢眼
    l = rng.uniform(0.84, 0.93)   # 高亮度 → 浅色
    fill = colorsys.hls_to_rgb(h, l, s)
    edge = colorsys.hls_to_rgb(h, max(0.30, l - 0.45), min(0.65, s + 0.15))
    def _hex(c):
        return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)
    return _hex(fill), _hex(edge)


def build_palette(devices, seed=None):
    """为每种设备类型随机分配一个浅色；同类型同色。返回 {role: (fill, edge)}。"""
    rng = random.Random(seed) if seed is not None else random.Random()
    roles = sorted({normalize_role(d) for d in devices.values()})
    palette = {}
    for r in roles:
        if r == "internet":
            palette[r] = ("#E8E8E8", "#7A7A7A")  # 互联网固定浅灰，不出彩
        else:
            palette[r] = pastel_color(rng)
    return palette


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

    def _norm_isp(h):
        # 出口对端常写成 ISP1/ISP2/Internet/isp-x 等，统一归一化到 Internet 云节点
        if "Internet" in devices and (
            h in ("Internet", "internet") or (h or "").lower().startswith("isp")
        ):
            return "Internet"
        return h

    for lk in model.get("links", []):
        a = lk.get("a", "")
        b = lk.get("b", "")
        if not a or not b:
            continue
        ha, ia = (a.split(":") + [None])[:2] if ":" in a else (a, None)
        hb, ib = (b.split(":") + [None])[:2] if ":" in b else (b, None)
        ha, hb = _norm_isp(ha), _norm_isp(hb)
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


def assign_positions(devices, links):
    """分层布局：主层（互联网→出口→防火墙→核心→汇聚→接入）纵向排列；
    server 设备侧挂在其锚点（优先防火墙，其次路由器/核心）旁边，避免连线穿越其他设备。"""
    main_roles = [r for r in LAYER_ORDER if r != "server"]
    # ---- 主层纵向布局 ----
    layers = {}  # role -> [hostname]
    for hn, dev in devices.items():
        r = normalize_role(dev)
        if r == "server":
            continue
        layers.setdefault(r, []).append(hn)
    pos = {}
    layer_y = {}
    y_top = 0.0
    for r in main_roles:
        members = layers.get(r, [])
        if not members:
            continue
        members_sorted = sorted(members, key=lambda h: (len(h), h))
        widths = [size_of(normalize_role(devices[h]))[0] for h in members_sorted]
        total_w = sum(widths) + NODE_GAP * (len(members_sorted) - 1)
        x = -total_w / 2
        layer_y[r] = y_top
        for i, hn in enumerate(members_sorted):
            w = widths[i]
            pos[hn] = (x + w / 2, y_top)
            x += w + NODE_GAP
        y_top -= LAYER_GAP

    # ---- server 侧挂：找到每台 server 的锚点设备 ----
    servers = [hn for hn, dev in devices.items() if normalize_role(dev) == "server"]
    if servers:
        # 建立邻接表（忽略管理链路）
        adj = {}
        for ha, hb, k, ia, ib, net in links:
            if k == "mgmt":
                continue
            adj.setdefault(ha, set()).add(hb)
            adj.setdefault(hb, set()).add(ha)
        # 锚点优先级：防火墙 > 出口路由器 > 核心 > 汇聚 > 接入 > 其他
        anchor_prio = {"fw": 0, "router": 1, "core": 2, "agg": 3, "access": 4}
        server_pos = {}
        # BFS 沿 server 边连通分组（避免 DB1→WEB1→FW1 链式中 DB1 找不到锚点）
        visited = set()
        groups = []  # [(anchor, [servers])]
        for s in sorted(servers):
            if s in visited:
                continue
            comp = []
            stack = [s]
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                comp.append(cur)
                for nb in adj.get(cur, set()):
                    if normalize_role(devices[nb]) == "server" and nb not in visited:
                        stack.append(nb)
            # 整组找唯一锚点
            anchor, best_prio = None, 99
            for cs in comp:
                for nb in adj.get(cs, set()):
                    r = normalize_role(devices[nb])
                    if r == "server":
                        continue
                    prio = anchor_prio.get(r, 10)
                    if prio < best_prio:
                        anchor, best_prio = nb, prio
            groups.append((anchor, sorted(comp)))
        # 放置：锚点左侧或右侧（跟锚点水平位置走，锚偏左放左、偏右放右）
        for anchor, group in groups:
            if anchor is None or anchor not in pos:
                continue
            ax, ay = pos[anchor]
            aw, ah = size_of(normalize_role(devices[anchor]))
            # 决定左右：锚点 x<0 放左，否则放右
            side = -1 if ax < 0 else 1
            # 组内服务器从锚点外侧开始，横向排开
            sw = max(size_of(normalize_role(devices[s]))[0] for s in group)
            x_cursor = ax + side * (aw / 2 + NODE_GAP + sw / 2)
            y_cursor = ay
            for s in sorted(group):
                sw_s, sh_s = size_of(normalize_role(devices[s]))
                server_pos[s] = (x_cursor, y_cursor)
                x_cursor += side * (sw_s + NODE_GAP * 0.6)
        # 无锚点的 server 放最底部
        bottom_y = y_top + LAYER_GAP * 0.5
        orphan = [s for s in servers if s not in server_pos]
        if orphan:
            total_w = sum(size_of(normalize_role(devices[s]))[0] for s in orphan) \
                      + NODE_GAP * (len(orphan) - 1)
            x = -total_w / 2
            for s in sorted(orphan):
                w_s = size_of(normalize_role(devices[s]))[0]
                server_pos[s] = (x + w_s / 2, bottom_y)
                x += w_s + NODE_GAP
        pos.update(server_pos)
    return pos, layer_y


def draw_device(ax, x, y, role, label, sublabel, palette):
    shape = shape_of(role)
    w, h = size_of(role)
    fill, edge = palette[role]
    half_w, half_h = w / 2, h / 2

    if shape == "cloud":
        # 云形：三个椭圆组合
        for cx, cw, ch in ((x - 0.6, w * 0.42, h * 0.62),
                           (x + 0.6, w * 0.42, h * 0.62),
                           (x, w * 0.55, h * 0.72)):
            e = Ellipse((cx, y), cw, ch, fc=fill, ec=edge, lw=1.2, zorder=3)
            ax.add_patch(e)
    elif shape == "ellipse":
        e = Ellipse((x, y), w * 0.92, h * 0.92, fc=fill, ec=edge, lw=1.5, zorder=3)
        ax.add_patch(e)
    elif shape == "vrect":
        # 服务器：竖矩形 + 内部 1U 分隔线
        r = Rectangle((x - half_w, y - half_h), w, h, fc=fill, ec=edge, lw=1.5, zorder=3)
        ax.add_patch(r)
        for i in (1, 2):
            yy = y - half_h + i * h / 3
            ax.plot([x - half_w + 0.15, x + half_w - 0.15], [yy, yy],
                    color=edge, lw=0.8, zorder=4)
    else:  # square / l2 / l3 → 圆角矩形（正方形或黄金矩形）
        r = FancyBboxPatch((x - half_w, y - half_h), w, h,
                           boxstyle="round,pad=0.06,rounding_size=0.18",
                           fc=fill, ec=edge, lw=1.5, zorder=3)
        ax.add_patch(r)

    # 主标签（hostname）
    ax.text(x, y + h * 0.10, label, ha="center", va="center",
            fontsize=9.5, fontweight="bold", color="#222222", zorder=5)
    # 副标签（型号，单行；只在节点较高时显示避免与链路标注重叠）
    if h >= 1.5:
        ax.text(x, y - h * 0.30, sublabel, ha="center", va="center",
                fontsize=7, color="#555555", zorder=5)


def draw_link(ax, p1, p2, kind, iface_a, iface_b, net):
    (x1, y1), (x2, y2) = p1, p2
    if kind == "agg":
        # 聚合/堆叠 = 两根平行细线（表示两条物理链路捆绑），间距 0.15 避免合成一根粗线
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        ux, uy = -dy / length, dx / length  # 垂直单位向量
        off = 0.15
        for s in (-1, 1):
            ax.plot([x1 + ux * off * s, x2 + ux * off * s],
                    [y1 + uy * off * s, y2 + uy * off * s],
                    color="#2F9E77", lw=1.7, ls="-", zorder=1)
    elif kind == "mgmt":
        color, lw, ls = "#9A9A9A", 1.8, "--"
        ax.plot([x1, x2], [y1, y2], color=color, lw=lw, ls=ls, zorder=1)
    else:
        color, lw, ls = "#555555", 2.0, "-"
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
                fontsize=7.5, color="#666666",
                bbox=dict(fc="white", ec="none", alpha=0.75, pad=0.4), zorder=6)


def draw_legend(ax, palette, has_roles):
    handles = []
    # 设备类型（只列出实际出现的）
    for role in LAYER_ORDER:
        if role not in has_roles:
            continue
        shape = shape_of(role)
        fill, edge = palette[role]
        if shape == "ellipse":
            handles.append(Line2D([0], [0], marker="o", color="w", markerfacecolor=fill,
                                  markeredgecolor=edge, markersize=9, label=SHAPE_CN[shape]))
        elif shape == "cloud":
            handles.append(Line2D([0], [0], marker="o", color="w", markerfacecolor=fill,
                                  markeredgecolor=edge, markersize=9, label=SHAPE_CN[shape]))
        else:
            w, h = size_of(role)
            label = "防火墙" if role == "fw" else SHAPE_CN[shape]
            if role == "access":
                label = "二层交换机"
            elif role in ("core", "agg"):
                label = "三层交换机"
            handles.append(Line2D([0], [0], marker="s", color="w", markerfacecolor=fill,
                                  markeredgecolor=edge, markersize=9, label=label))
    handles.append(Line2D([0], [0], color="#555555", lw=2.0, label="普通链路"))
    handles.append(Line2D([0], [0], color="#2F9E77", lw=2.0, label="聚合/堆叠（双物理链路）"))
    handles.append(Line2D([0], [0], color="#9A9A9A", lw=1.8, ls="--", label="管理链路"))
    leg = ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.03),
                    fontsize=7.5, framealpha=0.92, ncol=3,
                    handlelength=2.4, handletextpad=1.0, columnspacing=2.0,
                    borderpad=0.8)
    leg.get_frame().set_edgecolor("#CCCCCC")


def compute_canvas(devices, pos):
    """根据节点实际边界 + 链路标注空间计算画布范围（弹性，不留大量空白）。"""
    xs, ys = [], []
    for hn, dev in devices.items():
        if hn not in pos:
            continue
        x, y = pos[hn]
        w, h = size_of(normalize_role(dev))
        xs.extend([x - w / 2, x + w / 2])
        ys.extend([y - h / 2, y + h / 2])
    # 标题在上方、图例在下方需额外留白
    xmin, xmax = min(xs) - PAD, max(xs) + PAD
    ymin, ymax = min(ys) - PAD - 1.2, max(ys) + PAD + 2.6
    return xmin, xmax, ymin, ymax


def check_uplink_redundancy(devices, links):
    """检查接入层设备上联数量：双核心时接入应双上联（单上联 = 无冗余，给出 WARN）。"""
    warnings = []
    core_hosts = {hn for hn, d in devices.items() if normalize_role(d) in ("core", "agg")}
    access_hosts = {hn for hn, d in devices.items() if normalize_role(d) == "access"}
    if len(core_hosts) < 2 or not access_hosts:
        return warnings  # 单核心或没有接入设备，不适用该检查
    uplink = {hn: set() for hn in access_hosts}
    for ha, hb, k, ia, ib, net in links:
        if k == "mgmt":
            continue
        if ha in access_hosts and hb in core_hosts:
            uplink[ha].add(hb)
        if hb in access_hosts and ha in core_hosts:
            uplink[hb].add(ha)
    for hn, cores in sorted(uplink.items()):
        if len(cores) < 2:
            warnings.append("接入设备 %s 仅上联 %s（%s），双核心下建议双上联以保证冗余"
                            % (hn, "、".join(sorted(cores)) if cores else "无", "->".join(sorted(cores)) if cores else "未连接核心"))
    return warnings


def build(model, out_path, dpi=150, title=None, seed=None):
    font_name = setup_fonts()
    devices = collect_devices(model)
    links = collect_links(model, devices)
    for w in check_uplink_redundancy(devices, links):
        sys.stderr.write("WARN: %s\n" % w)
    palette = build_palette(devices, seed=seed)
    pos, layer_y = assign_positions(devices, links)
    xmin, xmax, ymin, ymax = compute_canvas(devices, pos)

    # 弹性画布：figsize 由数据范围决定，密度一致（每英寸 UNITS_PER_INCH 个数据单位）
    fig_w = (xmax - xmin) / UNITS_PER_INCH
    fig_h = (ymax - ymin) / UNITS_PER_INCH
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.axis("off")
    ax.set_aspect("equal")  # 保证形状不变形（圆是圆、黄金比是黄金比）

    proj = (model.get("meta") or {}).get("project_name", "网络项目")
    ax.set_title(title or ("%s —— 网络拓扑图" % proj), fontsize=13, fontweight="bold", pad=14)

    # 画链路（先画线，再画节点盖在上面，层次更干净）
    for (ha, hb, kind, ia, ib, net) in links:
        if ha in pos and hb in pos:
            draw_link(ax, pos[ha], pos[hb], kind, ia, ib, net)

    # 画节点
    has_roles = set()
    for hn, dev in devices.items():
        if hn not in pos:
            continue
        x, y = pos[hn]
        role = normalize_role(dev)
        has_roles.add(role)
        model_name = dev.get("model") or ""
        # 副标签只显示型号（角色已由形状/图例表达）
        sub = model_name if model_name else ""
        draw_device(ax, x, y, role, hn, sub, palette)

    draw_legend(ax, palette, has_roles)

    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    # 用 PIL 读实际像素尺寸
    try:
        from PIL import Image
        w_px, h_px = Image.open(out_path).size
    except Exception:
        w_px, h_px = int(fig_w * dpi), int(fig_h * dpi)
    print("OK: 已生成拓扑图 -> %s (%dx%d px)" % (out_path, w_px, h_px))
    if font_name:
        print("INFO: 使用中文字体 %s" % font_name)


def main():
    ap = argparse.ArgumentParser(description="网络拓扑图生成器（模型 → 拓扑 PNG）")
    ap.add_argument("model", nargs="?", help="项目模型 JSON 路径")
    ap.add_argument("-o", "--out", default="拓扑图.png", help="输出 PNG 路径（默认 拓扑图.png）")
    ap.add_argument("--dpi", type=int, default=150, help="图片分辨率（默认 150）")
    ap.add_argument("--title", default=None, help="自定义标题（默认取项目名）")
    ap.add_argument("--seed", type=int, default=None, help="配色随机种子（固定可复现）")
    ap.add_argument("--list", action="store_true", help="仅列出将绘制的设备/链路")
    ap.add_argument("--demo", action="store_true", help="用内置示例绘制演示拓扑（固定配色）")
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
                {"hostname": "ASW3", "role": "access", "role_cn": "二层接入", "model": "华为 S2700"},
                {"hostname": "WEB1", "role": "server", "role_cn": "DMZ服务器", "model": "Web"},
                {"hostname": "DB1", "role": "server", "role_cn": "数据库", "model": "DB"},
            ],
            "links": [
                # 出口层
                {"a": "Internet:GE0/0/0", "b": "AR1:GE0/0/0", "type": "static"},
                {"a": "Internet:GE0/0/0", "b": "AR2:GE0/0/0", "type": "static"},
                # 出口 → 防火墙（主 + 交叉冗余）
                {"a": "AR1:GE0/0/1", "b": "FW1:GE1/0/0", "type": "static"},
                {"a": "AR2:GE0/0/1", "b": "FW2:GE1/0/0", "type": "static"},
                {"a": "AR1:GE0/0/2", "b": "FW2:GE1/0/3", "type": "static"},   # 交叉
                {"a": "AR2:GE0/0/2", "b": "FW1:GE1/0/3", "type": "static"},   # 交叉
                # 防火墙双机热备聚合（心跳/状态同步）
                {"a": "FW1:GE1/0/4", "b": "FW2:GE1/0/4", "type": "eth-trunk", "id": 2},
                # 防火墙 → 核心（主 + 交叉冗余）
                {"a": "FW1:GE1/0/1", "b": "DSW1:GE0/0/1", "type": "static"},
                {"a": "FW2:GE1/0/1", "b": "DSW2:GE0/0/1", "type": "static"},
                {"a": "FW1:GE1/0/5", "b": "DSW2:GE0/0/5", "type": "static"},   # 交叉
                {"a": "FW2:GE1/0/5", "b": "DSW1:GE0/0/5", "type": "static"},   # 交叉
                # 核心间聚合
                {"a": "DSW1:GE0/0/24", "b": "DSW2:GE0/0/24", "type": "eth-trunk", "id": 1},
                # 核心 → 接入（双上联）
                {"a": "DSW1:GE0/0/2", "b": "ASW1:GE0/0/23", "type": "static"},
                {"a": "DSW2:GE0/0/2", "b": "ASW1:GE0/0/24", "type": "static"},
                {"a": "DSW1:GE0/0/3", "b": "ASW2:GE0/0/23", "type": "static"},
                {"a": "DSW2:GE0/0/3", "b": "ASW2:GE0/0/24", "type": "static"},
                {"a": "DSW1:GE0/0/4", "b": "ASW3:GE0/0/23", "type": "static"},
                {"a": "DSW2:GE0/0/4", "b": "ASW3:GE0/0/24", "type": "static"},
                # DMZ
                {"a": "FW1:GE1/0/2", "b": "WEB1:eth0", "type": "static"},
                {"a": "WEB1:eth1", "b": "DB1:eth0", "type": "static"},
            ],
        }
        model = demo
        if args.seed is None:
            args.seed = 42  # demo 固定配色，便于复现
    else:
        with open(args.model, "r", encoding="utf-8") as f:
            model = json.load(f)

    devices = collect_devices(model)
    links = collect_links(model, devices)

    if args.list:
        print("== 设备 ==")
        for hn, dev in devices.items():
            print("  %-12s %s" % (hn, SHAPE_CN.get(shape_of(normalize_role(dev)), "设备")))
        print("== 链路 ==")
        for ha, hb, k, ia, ib, net in links:
            print("  %s <-> %s  [%s]" % (ha, hb, k))
        for w in check_uplink_redundancy(devices, links):
            print("WARN: %s" % w)
        return

    build(model, args.out, dpi=args.dpi, title=args.title, seed=args.seed)


if __name__ == "__main__":
    main()
