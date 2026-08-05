# Web 命令查证方法（思科 / 华为 / 华三）

当设备型号不在 `references/cisco_cmds.md` / `huawei_cmds.md` / `h3c_cmds.md` 覆盖范围内，或担心新机型命令有细微差异（VRP 版本、IOS-XE 与经典 IOS、Comware V7/V9 等）时，按本文件上网查证，确保写出的配置命令准确可落地。

适用时机：阶段 5（可行性核查）与阶段 7（写配置）前各做一次"命令可得性检查"。

---

## 1. 总流程

```
遍历所有设备型号 → 标记"记忆内 / 待查证"
   → WebSearch 检索官方文档（检索式见下）
   → WebFetch 打开最相关官方页，提取命令片段
   → 用于写配置（官方不可达则退查社区并标注）
   → 反复用到的已验证命令补充进 references/*.md（SkillManage 累积）
   → 向用户说明"已联网核对 X 型号命令"
```

原则：
- **优先官方**：厂商 Configuration Guide / Command Reference 最权威。
- **明确标注**：凡官方页不可达、只能用社区/博客来源的，在配置文件注释里写"命令未经官方页面二次确认，部署前请在真机/模拟器核对"。
- **查证不等于决策**：命令准确性与"是否做 NAT/选什么路由协议"是两回事；关键设计决策仍须用户在阶段 3/4/5 确认。

---

## 2. 思科 Cisco

官方入口：
- 配置指南总库：https://www.cisco.com/c/en/us/support/docs
- 产品文档（按产品搜）：https://www.cisco.com/c/en/us/support
- IOS XE / IOS 命令参考：在支持页搜索 "Cisco <系列> Configuration Guide"

WebSearch 检索式（按场景选）：
- `"Cisco <型号> configuration guide CLI"`（如 `Cisco Catalyst 2960 configuration guide`）
- `"Cisco <系列> <feature> configuration example"`（如 `Cisco ISR 4000 NAT configuration example`）
- `"Cisco IOS XE <feature> command reference"`（新机型多用 IOS XE）
- `"site:cisco.com <型号> <feature>"`（限定官方域）

常见特性查证点：VLAN/Trunk、OSPF、VRRP/HSRP、LACP(EtherChannel)、ACL、NAT(PAT)、DHCP Server/Relay、端口安全、DHCP Snooping、DAI、802.1x、SSH/AAA、SNMP/Syslog、BFD/NQA。

> 注意经典 IOS 与 IOS-XE 差异：如 `ip nat inside/outside` 基本一致，但 AAA/接口命名、license 可能不同；新平台查 IOS-XE 文档。

---

## 3. 华为 Huawei

官方入口：
- 企业业务文档中心：https://support.huawei.com/enterprise/ （部分需区域/登录）
- 配置实例库：在文档中心搜 "产品 + 配置指南 + <特性>"
- CE 系列（数据中心交换机）：搜 "CE6800 / CE12800 配置指南"
- USG 防火墙：搜 "USG6000 配置指南 / 命令参考"，HRP 双机热备查"双机热备"章节

WebSearch 检索式：
- `"华为 <型号> 配置指南 <特性>"`（如 `华为 S5735 配置指南 VLAN`）
- `"华为 <型号> 命令参考 <特性>"`
- `"Huawei <model> configuration guide <feature>"`
- `"site:support.huawei.com <型号> <feature>"`

常见特性查证点（VRP）：
- 交换机：VLAN/Trunk、MSTP（注意 `stp instance` 与根桥 `stp root primary`）、VRRP（含 `vrrp vrid track` 上行跟踪）、Eth-Trunk(LACP，含 `load-balance src-dst-ip`)、VLANIF 三层接口、OSPF、DHCP（全局地址池 + `dhcp select global` / relay `dhcp select relay`）、端口安全（`port-security` / sticky）、DHCP Snooping + DAI（`arp anti-attack` / `dhcp snooping` / `arp detect`）、802.1x（`dot1x` + RADIUS 模板）、SSH/AAA、SNMP/Syslog、BFD。
- 防火墙 USG：安全域（trust/untrust/dmz）、安全策略（`security-policy`）、NAT（`nat-policy` / `source-nat`）、HRP（`hrp` + 会话同步）、ASPFF、AAA。

> 注意 VRP 版本差异：老 VRPv5 与新 VRPv8（CE 系列）命令差异较大（如 DAI 在 CE 可能是 `arp dynamic inspection`，老交换机是 `arp anti-attack`）；务必查对应版本文档。查到后在配置注释里注明适用 VRP 版本。

---

## 4. 华三 H3C

官方入口：
- H3C 文档中心：https://www.h3c.com/cn/ （支持 → 文档中心）
- 配置指导：搜 "H3C <系列> 配置指导 <特性>"
- Comware V7/V9 命令参考

WebSearch 检索式：
- `"H3C <型号> 配置指导 <特性>"`（如 `H3C S6850 配置指导 VLAN`）
- `"H3C <型号> 命令参考 <特性>"`
- `"H3C Comware V7 <feature> configuration"`
- `"site:h3c.com <型号> <feature>"`

常见特性查证点（Comware）：
- 交换机：VLAN/Trunk、MSTP、VRRP、链路聚合（Aggregation Group / `link-aggregation` + LACP）、VLAN 接口（VLAN-interface）、OSPF、DHCP Server/Relay（`dhcp server` / `dhcp relay`）、端口安全（`port-security` + `port-security mac-address sticky`）、DHCP Snooping + 动态 ARP 检测、802.1x（`dot1x` + RADIUS scheme）、SSH/AAA、SNMP/Syslog、BFD/NQA。
- 路由器（MSR 等）：接口/IP、OSPF、NAT（`nat outbound` + ACL）、默认路由、`track` + NQA 实现出口切换。

> 注意 Comware V5/V7/V9 差异：V5 与 V7 的端口安全、聚合、AAA 命令差异明显；务必查对应版本。查到后在配置注释里注明适用 Comware 版本。

---

## 5. WebFetch 提取要点

打开官方页后，重点提取：
- **完整命令块**（含进入视图的层级，如 `system-view` → `interface ...` → 具体命令）；
- **命令上下文/前置依赖**（如要先建 VLAN 再配 trunk、要先建 RADIUS scheme 再绑 dot1x）；
- **版本/license 限制**（避免写出型号不支持的命令）。

若页面是 PDF 或登录墙，WebFetch 可能取不到全文，则改用 WebSearch 的摘要片段拼接，或退查厂商社区/技术博客，并标注来源未经官方二次确认。

---

## 6. 把验证命令沉淀回技能（可选但推荐）

凡同一型号/特性被反复用到，把验证过的命令片段补充进对应 `references/*.md`，下次直接复用，减少对网络的依赖。补充方式：用 SkillManage 修改对应参考文件（或追加一节"已查证型号"）。
