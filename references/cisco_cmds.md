# 思科（Cisco IOS / IOS-XE）配置命令速查

> **定位：三方对比中的对照参考。** 命令来源采用三方交叉验证：AI 记忆 + 网络搜索同时参考，冲突时查本文件三方对比，**以网络搜索结果为准**；网络不可用时本文件与记忆对比、以记忆为准并告知用户冲突项。本文件只覆盖思科常见命令，遇型号/版本差异（IOS vs IOS-XE）以网络查证对应版本为准。

适用：Catalyst 交换机（如 C2960 二层、C9200/C9300 三层）、ISR 路由器。注意 **C2960 为纯二层，不能运行 OSPF/三层路由**，三层网关需上移至三层交换机或路由器。

> **注释符约定**：本文件所有注释/分段符统一用 `!`（思科标准注释符，行首 `!` 整行被忽略）。

## 1. 基础
```
hostname SW1
!
enable secret Str0ng@Pass    ! 特权加密密码
!
username admin privilege 15 secret Str0ng@Pass
line vty 0 4
 login local
 transport input ssh
line console 0
 login local
!
service password-encryption
ip domain-name lab.local
crypto key generate rsa modulus 2048
ip ssh version 2
```

## 2. 管理 VLAN / SVI
```
vlan 10
 name MGMT
!
interface Vlan10
 ip address 10.10.10.11 255.255.255.0
 no shutdown
ip default-gateway 10.10.10.1   ! 二层交换机用 default-gateway
```

## 3. 二层接口（Access / Trunk）
```
interface GigabitEthernet0/1
 switchport mode access
 switchport access vlan 20
 spanning-tree portfast
!
interface GigabitEthernet0/24
 switchport trunk encapsulation dot1q
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
```

## 4. EtherChannel（LACP，等价华为 Eth-Trunk）
```
interface Port-channel1
 switchport trunk encapsulation dot1q
 switchport mode trunk
!
interface range Gi0/23 , Gi0/24
 channel-group 1 mode active   ! LACP 主动
```

## 5. STP（根桥指定）
```
spanning-tree mode rapid-pvst
spanning-tree vlan 1-4094 priority 4096   ! 设为根桥（值越小越优）
```

## 6. 三层交换机：SVI 网关 + OSPF
```
interface Vlan20
 ip address 10.20.0.1 255.255.255.0
 standby 20 ip 10.20.0.1   ! HSRP 虚拟网关（或改用 VRRP）
!
router ospf 1
 router-id 1.1.1.1
 network 10.0.0.0 0.255.255.255 area 0
 passive-interface Vlan10   ! 管理网段不建邻居
```

## 7. VRRP（思科也支持 VRRP，替代 HSRP）
```
interface Vlan20
 vrrp 20 ip 10.20.0.1
 vrrp 20 priority 120
 vrrp 20 track GigabitEthernet0/1 30   ! 上行 DOWN 降优先级
```

## 8. 静态路由 / 默认路由
```
ip route 0.0.0.0 0.0.0.0 200.1.1.2
```

## 9. ACL
```
access-list 2000 permit ip 192.168.0.0 0.0.255.255 any   ! 基础ACL(按编号,注意IOS标准ACL编号)
ip access-list extended DMZ-OUT
 deny ip any any
```

## 10. NAT（路由器，出方向 PAT）
```
interface GigabitEthernet0/0        ! 内网口
 ip nat inside
interface GigabitEthernet0/1        ! 外网口
 ip nat outside
!
ip nat inside source list 1 interface GigabitEthernet0/1 overload
access-list 1 permit 192.168.0.0 0.0.255.255
!
ip nat inside source static tcp 10.40.0.10 80 200.1.1.10 80   ! DMZ 静态映射
```

## 11. AAA / SNMP / Syslog
```
aaa new-model
aaa authentication login default local
snmp-server community public RO
snmp-server host 10.10.10.100 version 2c public
logging host 10.10.10.100
logging trap informational
```

## 12. BFD（接口下）
```
interface GigabitEthernet0/1
 bfd interval 100 min_rx 100 multiplier 3
```

## 13. 保存
```
write memory
# 或 copy running-config startup-config
```

> 注意：防火墙（ASA/Firepower）命令差异很大（nameif / security-level / object / access-group），若用户使用思科防火墙，另行检索 ASA 配置语法。
