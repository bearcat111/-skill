# 安全加固基线（增强轮次 · 安全加固）

本文件为「阶段 7 增强轮次 · 安全加固（8）」提供可套用的加固清单与命令样例。作为乙方安全服务交付时，建议对全网设备叠加此基线，并在文档中单列「安全加固说明」章节。命令按厂商分列，注释符遵循约定（思科=`!`、华为/华三=`#`）。

## 通用原则
- 禁用明文管理协议（Telnet / HTTP），仅保留 SSH v2；
- 管理平面与业务平面隔离，管理流量走独立管理 VLAN / 带外；
- 特权分级、空闲超时、登录失败锁定；
- 时钟同步（NTP）与日志审计（Syslog）开启；
- 控制平面限速/保护，防 CPU 耗尽类攻击。

## 思科 IOS（! 注释）
```
no ip http server
no ip http secure-server
line vty 0 4
 transport input ssh
 exec-timeout 10 0
 login block-for 120 attempts 5 within 60
!
ip ssh version 2
ntp server 10.100.100.100
logging host 10.100.100.100
logging trap informational
!
control-plane
 service-policy input CP-PROTECT
```

## 华为 VRP（# 注释）
```
undo http server
undo telnet server
#
stelnet server enable
ssh server version 2
#
user-interface vty 0 4
 idle-timeout 10 0
#
ntp-service unicast-server 10.100.100.100
info-center loghost 10.100.100.100
#
cpu-defend policy CP-PROTECT
 car 1 cir 64
```

## 华三 Comware（# 注释）
```
undo ip http enable
#
ssh server enable
ssh server version 2
#
user-interface vty 0 4
 idle-timeout 10 0
#
ntp-service unicast-server 10.100.100.100
info-center loghost 10.100.100.100
```

## 加固交付清单（自检）
- [ ] 已禁用 Telnet / HTTP（仅 SSH v2）
- [ ] 管理 VLAN 与业务 VLAN 分离
- [ ] 空闲超时 + 登录失败锁定
- [ ] NTP 时钟同步
- [ ] Syslog 上送日志服务器
- [ ] 控制平面保护 / 限速
- [ ] ACL 限制管理源（仅允许运维网段 SSH）
