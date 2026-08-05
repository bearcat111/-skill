#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_comments.py —— 按厂商归一化网络配置文件的注释符

问题背景：
    思科(IOS/IOS-XE)用 `!` 作注释/分段符；华为(VRP)与华三(Comware)用 `#`
    作注释/分段符（同时也是官方配置文件的段落分隔符）。华为/华三配置里若
    出现 `!`，真机会报 `Error: Unrecognized command`，可能中断粘贴部署。

功能：
    读取一个配置文件，把所有"以注释符开头的行"统一改成目标厂商的标准注释符。
    - 思科  -> `!`
    - 华为  -> `#`
    - 华三  -> `#`

判定规则：
    一行如果去除前导空白后以 `!` 或 `#` 开头，即视为注释行，将其首字符替换为
    目标厂商注释符；其余行原样保留。华为/华三里 `#` 也用于系统分段符，归一化
    不影响语义；思科里 `!` 仅作注释，同理。

用法：
    python normalize_comments.py --vendor huawei --in DSW1_三层交换机_v1.txt --in-place
    python normalize_comments.py --vendor cisco  --in R1.txt --out R1_fixed.txt

参数：
    --vendor   {cisco,huawei,h3c}   目标厂商（决定标准注释符）
    --in       FILE                 输入配置文件
    --out      FILE                 输出文件（默认同 --in，即预览不写盘）
    --in-place                    直接覆盖输入文件（等价于 --out 指向自身）
"""

import argparse
import os
import sys

COMMENT_CHAR = {
    "cisco": "!",
    "huawei": "#",
    "h3c": "#",
}


def normalize(text, vendor):
    target = COMMENT_CHAR[vendor]
    out_lines = []
    changed = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped and stripped[0] in ("!", "#"):
            if stripped[0] != target:
                # 保留首字符后的内容（含其后的空格与文字），仅替换首字符
                new_line = " " * (len(line) - len(stripped)) + target + stripped[1:]
                out_lines.append(new_line)
                changed += 1
                continue
        out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else ""), changed


def main():
    ap = argparse.ArgumentParser(description="按厂商归一化配置文件注释符")
    ap.add_argument("--vendor", required=True, choices=sorted(COMMENT_CHAR.keys()),
                    help="目标厂商：cisco / huawei / h3c")
    ap.add_argument("--in", dest="infile", required=True, help="输入配置文件")
    ap.add_argument("--out", dest="outfile", default=None, help="输出文件（默认预览，不写盘）")
    ap.add_argument("--in-place", dest="inplace", action="store_true",
                    help="直接覆盖输入文件")
    args = ap.parse_args()

    if not os.path.isfile(args.infile):
        sys.stderr.write("ERROR: 输入文件不存在: %s\n" % args.infile)
        sys.exit(2)

    with open(args.infile, "r", encoding="utf-8") as f:
        text = f.read()

    new_text, changed = normalize(text, args.vendor)
    target = COMMENT_CHAR[args.vendor]

    out_path = args.outfile if args.outfile else (args.infile if args.inplace else None)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        print("厂商=%s 标准注释符=%s | 已归一化 %d 行 -> %s" % (args.vendor, target, changed, out_path))
    else:
        print("厂商=%s 标准注释符=%s | 将归一化 %d 行（预览，未写盘）" % (args.vendor, target, changed))
        print("-" * 50)
        # 仅打印被改动/注释行，便于核对
        for line in new_text.splitlines():
            s = line.lstrip()
            if s and s[0] in ("!", "#"):
                print(line)


if __name__ == "__main__":
    main()
