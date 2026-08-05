# 部署验收清单（阶段 7.5）

在阶段 7 生成全部配置并导入设备（eve-ng / 真机）后，按本清单逐项验证"照着敲能跑起来"。每条均给出验证目标与查看命令（按厂商分列）。注释符约定：思科用 `!`，华为/华三用 `#`（仅说明文字，非配置）。

## 通用前置
- 设备已 `save` / `write memory`；
- PC 已获取地址（`ipconfig` / `ifconfig` 看是否拿到 `.101+`）；
- 从 PC `ping` 默认网关（VRRP 虚地址 `.254`）应通。

## 1. 连通性
- 目标：PC ↔ 网关、PC ↔ PC（跨 VLAN 经三层）、PC ↔ 出口/因特网（若做 NAT）。
- 命令：`ping <ip>`（三厂商通用）。

## 2. OSPF 邻居
- 目标：所有规划邻居进入 `Full`。
- 思科：`show ip ospf neighbor`
- 华为/华三：`display ospf peer brief`
- 异常：卡在 `2-Way`/`Exstart` → 检查互联 IP 同段、area 一致、接口是否被 `passive`、认证是否匹配。

## 3. VRRP 主备
- 目标：奇数 VLAN 主在 DSW1、偶数在 DSW2；上行 `track` 生效时正确倒换。
- 思科：`show vrrp brief`
- 华为/华三：`display vrrp brief`
- 验证：shutdown DSW1 上行口，对应 VLAN 的 Master 应切到 DSW2（优先级衰减后）。

## 4. DHCP 下发
- 目标：PC 拿到地址池范围内（`.101–.254`），网关为 VRRP 虚地址。
- 思科：`show ip dhcp binding`
- 华为：`display ip pool name <pool> used`
- 华三：`display dhcp server ip-in-use`
- 异常：拿不到 → 检查中继（`ip helper-address` / `dhcp relay server-address`）、地址池网段与 VLANIF 同段、DHCP Snooping trust 口。

## 5. NAT（若启用）
- 目标：内网访问外网时源地址被转换为公网地址。
- 思科：`show ip nat translations`
- 华为/华三：`display nat session brief`
- 验证：PC 访问外网，转换表应有对应条目。

## 6. 802.1x 认证（若启用）
- 目标：终端经 RADIUS 认证后才放行。
- 华为/华三：`display access-user` / `display dot1x`
- 思科：`show dot1x all` / `show authentication sessions`
- 异常：认证失败 → 检查 RADIUS 服务器可达、共享密钥、端口 `dot1x`/`authentication port-control` 已启用。

## 7. STP 根桥
- 目标：MST 实例 1 根=DSW1、实例 2 根=DSW2；接入边缘端口 `edged-port` 生效。
- 思科：`show spanning-tree mst`
- 华为/华三：`display stp root` / `display stp instance 1`

## 8. 链路聚合
- 目标：DSW 间 Eth-Trunk / LACP 成员全部 Selected。
- 华为：`display eth-trunk 1`
- 华三：`display link-aggregation verbose`
- 思科：`show etherchannel summary`

## 9. BFD / 故障检测
- 目标：BFD 会话 Up，故障 100ms×3 内切换。
- 华为/华三：`display bfd session all`
- 思科：`show bfd neighbors`

## 10. AAA / SSH 登录
- 目标：仅 SSH v2 可达，Telnet/HTTP 不可达；RADIUS 不可达时本地 admin 兜底。
- 验证：`ssh <user>@<mgmt-ip>` 成功；`telnet <mgmt-ip>` 应被拒。
- 华为/华三：`display ssh server status`；思科：`show ip ssh`。

## 验收结论模板
在「设计基线.md / 验收记录」中填写：每项 ✅/❌、异常与处理、遗留风险。全部 ✅ 视为部署成功，可交付。
