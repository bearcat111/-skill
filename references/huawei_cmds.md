# 华为（Huawei VRP）配置命令速查

适用：交换机（S2700/S5700/S6700/S7700）、路由器（AR 系列）、防火墙（USG6000）。华为 CLI 与思科差异明显，注意视图结构与命令字。

> **注释符约定**：本文件所有注释/分段符统一用 `#`。华为 VRP 不支持 `!` 作为注释（`!` 在真机/模拟器会报 `Error: Unrecognized command`），切勿在华为配置里使用 `!`。

## 1. 基础
```
sysname DSW1
#
aaa
 local-user admin password cipher Str0ng@Pass
 local-user admin service-type terminal ssh http
 local-user admin privilege level 15
#
user-interface con 0
 authentication-mode aaa
user-interface vty 0 4
 authentication-mode aaa
 protocol inbound ssh
#
rsa local-key-pair create
stelnet server enable
ssh user admin authentication-type password
```

## 2. VLAN / 管理
```
vlan batch 10 20 30 40
#
interface Vlanif10
 ip address 10.10.10.11 255.255.255.0
#
ip route-static 0.0.0.0 0.0.0.0 10.10.10.1
```

## 3. 二层接口（Access / Trunk）
```
interface GigabitEthernet0/0/1
 port link-type access
 port default vlan 20
 stp edged-port enable
#
interface GigabitEthernet0/0/24
 port link-type trunk
 port trunk allow-pass vlan 10 20 30 40
```

## 4. Eth-Trunk（LACP，等价 Cisco EtherChannel）
```
interface Eth-Trunk1
 port link-type trunk
 port trunk allow-pass vlan all
 mode lacp-static
#
interface GigabitEthernet0/0/23
 eth-trunk 1
interface GigabitEthernet0/0/24
 eth-trunk 1
```

## 5. 堆叠（iStack，盒式交换机）
```
stack
 stack member 1 priority 150
 stack member 2 priority 120
#
interface Stack-Port1/1
 port interface GigabitEthernet1/0/27 enable
 port interface GigabitEthernet1/0/28 enable
```

## 6. STP（根桥指定）
```
stp mode rstp
stp instance 1 root primary     # 设为主根桥
```

## 7. 三层网关 + OSPF
```
interface Vlanif20
 ip address 10.20.0.2 255.255.255.0
 vrrp vrid 20 virtual-ip 10.20.0.1
 vrrp vrid 20 priority 120
 vrrp vrid 20 track interface GigabitEthernet0/0/1 reduced 30
#
ospf 1 router-id 1.1.1.1
 area 0
  network 10.0.0.0 0.255.255.255
 silent-interface Vlanif10      # 管理网段不建邻居
```

## 8. VRRP
```
interface Vlanif20
 vrrp vrid 20 virtual-ip 10.20.0.1
 vrrp vrid 20 priority 120
 vrrp vrid 20 preempt-mode timer delay 20
```

## 9. 静态/默认路由
```
ip route-static 0.0.0.0 0.0.0.0 200.1.1.2
```

## 10. ACL（高级 ACL 用 3000+，基础用 2000+）
```
acl number 2000
 rule 5 permit source 192.168.0.0 0.0.255.255
#
acl number 3000
 rule 5 permit tcp destination 10.40.0.10 0 destination-port eq 80
 rule 10 deny ip
```

## 11. NAT（路由器/防火墙出方向 PAT）
```
acl number 2000
 rule 5 permit source 192.168.0.0 0.0.255.255
#
interface GigabitEthernet0/0/1        # 出接口
 nat outbound 2000
#
nat server global 200.1.1.10 inside 10.40.0.10        # DMZ 映射(防火墙语法略有差异)
```

## 12. USG6000 防火墙（安全域 + 安全策略 + HRP 热备）
```
firewall zone trust
 add interface GigabitEthernet1/0/1
firewall zone dmz
 add interface GigabitEthernet1/0/2
firewall zone untrust
 add interface GigabitEthernet1/0/0
#
security-policy
 rule name Untrust-to-DMZ
  source-zone untrust
  destination-zone dmz
  destination-address 10.40.0.10 32
  service http https
  action permit
 rule name DMZ-to-Trust-DB
  source-zone dmz
  destination-zone trust
  destination-address 10.50.0.0 24
  service mysql
  action permit
#
hrp enable
hrp interface GigabitEthernet1/0/3 remote 1.1.2.2   # 心跳
hrp priority 120                                    # 主
```

## 13. AAA / SNMP / Syslog
```
snmp-agent
snmp-agent community read public
snmp-agent target-host trap address udp-domain 10.10.10.100 params securityname public
info-center loghost 10.10.10.100
```

## 14. BFD
```
bfd
#
interface GigabitEthernet0/0/1
 bfd min-transmit-interval 100
 bfd min-receive-interval 100
 bfd detect-multiplier 3
```

## 15. 保存
```
save
```
