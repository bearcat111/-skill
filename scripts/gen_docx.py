#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_docx.py —— 网络项目部署文档生成器（由 network-deploy 技能调用）

用法：
    python gen_docx.py [项目模型.json] [输出.docx]

说明：
    - 第一个参数为 JSON 模型路径（默认 ./项目模型.json）
    - 第二个参数为输出 docx 路径（默认 ./项目设计文档.docx）
    - 依赖 python-docx；若缺失请先安装：
        venv/Scripts/pip install python-docx

JSON 模型结构（详见下方 EXAMPLE）：
{
  "meta": {
    "project_name": "XX园区三层网",
    "author": "AI",
    "date": "2026-08-05",
    "background": "背景描述",
    "objective": "建设目标",
    "architecture": "三层架构说明"
  },
  "topology": "ASCII 拓扑文本（用 \\n 换行）",
  "ledgers": [
    {
      "title": "设备台账总表",
      "columns": ["主机名","品牌型号","角色","管理IP","互联接口","VLAN","运行协议","账号/密码","备注"],
      "rows": [ ["DSW1","华为S5735","三层核心","10.10.10.11","GE0/0/1↔FW1","10,20,30","OSPF/VRRP","admin/***","主"] ]
    }
  ],
  "narrative": [
    {"title": "ACL 2000 说明", "body": "ACL 2000 用于出方向 NAT 地址池匹配……"},
    {"title": "Loopback 与 router-id", "body": "DSW1 的 Loopback0=1.1.1.1……"}
  ]
}
"""

import sys
import os
import json
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def ensure_docx():
    try:
        import docx  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "ERROR: 缺少 python-docx。请在托管虚拟环境中安装：\n"
            "  venv/Scripts/pip install python-docx\n"
        )
        sys.exit(2)
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    return Document, Pt, RGBColor, qn


def set_cjk(run, font="宋体"):
    """让 run 同时支持中文与西文显示。"""
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        from docx.oxml import OxmlElement
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    rfonts.set(qn('w:eastAsia'), font)
    rfonts.set(qn('w:ascii'), font)
    rfonts.set(qn('w:hAnsi'), font)


def build(json_path, out_path):
    Document, Pt, RGBColor, qn = ensure_docx()
    from docx.shared import Pt as _Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    with open(json_path, "r", encoding="utf-8") as f:
        model = json.load(f)

    doc = Document()

    # 默认正文字体
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        from docx.oxml import OxmlElement
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    rfonts.set(qn('w:eastAsia'), "宋体")

    meta = model.get("meta", {})
    project_name = meta.get("project_name", "网络项目")
    author = meta.get("author", "AI")
    date = meta.get("date", "")

    # 标题
    t = doc.add_heading(level=0)
    r = t.add_run(project_name + " —— 网络项目部署设计文档")
    set_cjk(r, "黑体")

    # 基本信息
    info = doc.add_paragraph()
    for label, key in [("项目名称", "project_name"), ("编制", "author"),
                       ("日期", "date"), ("背景", "background"),
                       ("目标", "objective"), ("架构", "architecture")]:
        if key in meta and meta[key]:
            p = doc.add_paragraph()
            rr = p.add_run(f"{label}：")
            set_cjk(rr, "黑体")
            rb = p.add_run(meta[key])
            set_cjk(rb, "宋体")

    # 拓扑图
    doc.add_heading("一、网络拓扑图", level=1)
    topo = model.get("topology", "")
    if topo:
        para = doc.add_paragraph()
        run = para.add_run(topo)
        run.font.name = "Consolas"
        run.font.size = Pt(9)
        # 等宽字体同时设置 eastAsia 为黑体以免中文错位
        rpr2 = run._element.get_or_add_rPr()
        rf2 = rpr2.find(qn('w:rFonts'))
        if rf2 is None:
            from docx.oxml import OxmlElement
            rf2 = OxmlElement('w:rFonts')
            rpr2.append(rf2)
        rf2.set(qn('w:eastAsia'), "宋体")
        rf2.set(qn('w:ascii'), "Consolas")
        rf2.set(qn('w:hAnsi'), "Consolas")

    # 台账表
    doc.add_heading("二、设备台账与配置总表", level=1)
    for idx, ledger in enumerate(model.get("ledgers", []), start=1):
        doc.add_heading(f"2.{idx} {ledger.get('title','台账')}", level=2)
        columns = ledger.get("columns", [])
        rows = ledger.get("rows", [])
        if not columns:
            continue
        table = doc.add_table(rows=1, cols=len(columns))
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        for i, col in enumerate(columns):
            hdr[i].text = ""
            pr = hdr[i].paragraphs[0].add_run(col)
            set_cjk(pr, "黑体")
            pr.bold = True
        for row in rows:
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = ""
                pr = cells[i].paragraphs[0].add_run(str(val))
                set_cjk(pr, "宋体")
        doc.add_paragraph("")

    # 文字详述
    doc.add_heading("三、项目详细说明", level=1)
    for item in model.get("narrative", []):
        h = doc.add_heading(item.get("title", "说明"), level=2)
        for run in h.runs:
            set_cjk(run, "黑体")
        body = item.get("body", "")
        for line in body.split("\n"):
            p = doc.add_paragraph(line if line else " ")
            for run in p.runs:
                set_cjk(run, "宋体")

    # 落款
    doc.add_paragraph("")
    foot = doc.add_paragraph(f"—— 本文档由 network-deploy 技能生成，含账号密码等敏感信息，请妥善保管。")
    for run in foot.runs:
        set_cjk(run, "宋体")
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)
    doc.save(out_path)
    print(f"OK: 已生成文档 -> {out_path}")


if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else "项目模型.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "项目设计文档.docx"
    if not os.path.exists(json_path):
        sys.stderr.write(f"ERROR: 找不到 JSON 模型文件: {json_path}\n")
        sys.exit(1)
    build(json_path, out_path)
