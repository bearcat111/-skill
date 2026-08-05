# -skill
网络项目部署技能，适配经典三层架构，根据项目需求文档生成项目设计文档与各设备配置文件，持续优化中......

# 结构
├── SKILL.md                      # 主流程驱动
├── references/
│   ├── workflow.md               # 各阶段细化清单+提问话术
│   ├── topology_examples.md      # 三层架构 ASCII 拓扑范例
│   ├── glossary.md                # ACL/Loopback/VRRP/OSPF cost 等解释话术
│   ├── cisco_cmds.md             # 思科命令速查
│   ├── huawei_cmds.md            # 华为命令速查（含 USG6000 防火墙）
│   └── h3c_cmds.md               # 华三命令速查
└── scripts/gen_docx.py           # Word 文档生成器（已实测可生成 .docx）
