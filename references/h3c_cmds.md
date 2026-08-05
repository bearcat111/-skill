# 华三（H3C Comware）配置命令速查

适用：交换机（S5x00/S7x00）、路由器（MSR 系列）。Comware 与华为 VRP 相似但命令字有差异（如 `port link-mode`、`vlan` 直接进、`sysname` 同）。

> **注释符约定**：本文件所有注释/分段符统一用 `#`。华三 Comware 不支持 `!` 作为注释（`!` 在真机/模拟器会报 `Error: Unrecognized command`），切勿在华三配置里使用 `!`。

## 1. 基础
```
sysname AR1
#
local-user admin class manage
 password simple Str0ng@Pass
 service-type ssh terminal
 authorization-attribute user-role network-admin
#
user-interface vty 0 4
 authentication-mode scheme
 protocol inbound ssh
user-interface aux 0
 authentication-mode scheme
#
public-key local create rsa
ssh server enable
```

## 2. VLAN / 管理
```
vlan 10
#
interface Vlan-interface10
 ip address 10.10.10.11 255.255.255.0
#
ip route-static 0.0.0.0 0.0.0.0 10.10.10.1
```

## 3. 二层接口（Access / Trunk）
```
interface GigabitEthernet1/0/1
 port link-mode bridge
 port access vlan 20
 stp edged-port
#
interface GigabitEthernet1/0/24
 port link-mode bridge
 port link-type trunk
 port trunk permit vlan 10 20 30 40
```

## 4. 链路聚合（LACP，等价 Eth-Trunk）
```
interface Bridge-Aggregation1
 port link-type trunk
 port trunk permit vlan all
 link-aggregation mode dynamic
#
interface GigabitEthernet1/0/23
 port link-aggregation group 1
interface GigabitEthernet1/0/24
 port link-aggregation group 1
```

## 5. IRF（虚拟化堆叠，等价 iStack）
```
irf member 1 priority 32
irf member 2 priority 30
#
interface Ten-GigabitEthernet1/0/27
 shutdown
 irf-port 1/1
  port group interface Ten-GigabitEthernet1/0/27
#
irf-port-configuration active
```

## 6. STP（根桥指定）
```
stp mode rstp
stp instance 0 root primary
```

## 7. 三层网关 + OSPF
```
interface Vlan-interface20
 ip address 10.20.0.2 255.255.255.0
 vrrp vrid 20 virtual-ip 10.20.0.1
 vrrp vrid 20 priority 120
#
ospf 1 router-id 1.1.1.1
 area 0.0.0.0
  network 10.0.0.0 0.255.255.255
 silent-interface Vlan-interface10
```

## 8. VRRP
```
interface Vlan-interface20
 vrrp vrid 20 virtual-ip 10.20.0.1
 vrrp vrid 20 priority 120
 vrrp vrid 20 preempt-mode delay 20
```

## 9. 静态/默认路由
```
ip route-static 0.0.0.0 0.0.0.0 200.1.1.2
```

## 10. ACL（高级 3000+，基本 2000+）
```
acl basic 2000
 rule 5 permit source 192.168.0.0 0.0.255.255
#
acl advanced 3000
 rule 5 permit tcp destination 10.40.0.10 0 destination-port eq 80
 rule 10 deny ip
```

## 11. NAT（路由器出方向 PAT）
```
acl basic 2000
 rule 5 permit source 192.168.0.0 0.0.255.255
#
interface GigabitEthernet0/0/1        ! 出接口
 nat outbound 2000
#
nat server protocol tcp global 200.1.1.10 80 inside 10.40.0.10 80   ! DMZ 映射
```

## 12. AAA / SNMP / Syslog
```
snmp-agent
snmp-agent community read public
snmp-agent target-host trap address udp-domain 10.10.10.100 params securityname public
info-center loghost 10.10.10.100
```

## 13. BFD
```
bfd
#
interface GigabitEthernet0/0/1
 bfd min-transmit-interval 100
 bfd min-receive-interval 100
 bfd detect-multiplier 3
```

## 14. 保存
```
save
```
