#!/usr/bin/env python3
"""
Inter-Path Latency Analyzer

分析 TX/RX 日志中的高延迟包，计算各阶段延迟分布，
包括物理网络延迟推算（TX Inter-Path - RX Total RTT）。

输出一张完整的延迟分段汇总表（CSV格式）。

用法:
    python3 interpath_latency_analyzer.py --tx tx.log --rx rx.log --csv output.csv
"""

import re
import csv
import json
import argparse
from dataclasses import dataclass
from typing import Optional
from collections import defaultdict


@dataclass
class SessionData:
    """Session 数据"""
    timestamp: str
    seq: int
    icmp_id: int
    path1_total: float  # us
    path2_total: float  # us
    total_rtt: float    # us
    inter_path: float   # us
    path1_stages: dict  # stage -> latency
    path2_stages: dict  # stage -> latency


def parse_log_file(filepath: str) -> dict[int, SessionData]:
    """解析日志文件，返回 {seq: SessionData}"""
    sessions = {}

    with open(filepath, 'r') as f:
        content = f.read()

    # 按 session 分割
    session_blocks = re.split(r'={50,}', content)

    for block in session_blocks:
        if '=== ICMP RTT Trace:' not in block:
            continue

        # 解析时间戳
        ts_match = re.search(r'=== ICMP RTT Trace: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)', block)
        if not ts_match:
            continue
        timestamp = ts_match.group(1)

        # 解析 Session ID 和 Seq
        session_match = re.search(r'Session:.*\(ID: (\d+), Seq: (\d+)\)', block)
        if not session_match:
            continue
        icmp_id = int(session_match.group(1))
        seq = int(session_match.group(2))

        # 解析 Path 1 Total
        path1_match = re.search(r'Total Path 1:\s*([\d.]+)\s*us', block)
        path1_total = float(path1_match.group(1)) if path1_match else 0.0

        # 解析 Path 2 Total
        path2_match = re.search(r'Total Path 2:\s*([\d.]+)\s*us', block)
        path2_total = float(path2_match.group(1)) if path2_match else 0.0

        # 解析 Total RTT
        rtt_match = re.search(r'Total RTT \(Path1 Start to Path2 End\):\s*([\d.]+)\s*us', block)
        total_rtt = float(rtt_match.group(1)) if rtt_match else 0.0

        # 解析 Inter-Path Latency
        inter_match = re.search(r'Inter-Path Latency \(P1 end -> P2 start\):\s*([\d.]+)\s*us', block)
        inter_path = float(inter_match.group(1)) if inter_match else 0.0

        # 解析各 stage 延迟
        path1_stages = {}
        path2_stages = {}

        # Path 1 stages
        for match in re.finditer(r'\[\s*(\d+)->(\d+)\s*\].*?:\s*([\d.]+)\s*us', block):
            stage_from = int(match.group(1))
            stage_to = int(match.group(2))
            latency = float(match.group(3))
            if stage_from < 7:  # Path 1
                path1_stages[f"{stage_from}->{stage_to}"] = latency
            else:  # Path 2
                path2_stages[f"{stage_from}->{stage_to}"] = latency

        sessions[seq] = SessionData(
            timestamp=timestamp,
            seq=seq,
            icmp_id=icmp_id,
            path1_total=path1_total,
            path2_total=path2_total,
            total_rtt=total_rtt,
            inter_path=inter_path,
            path1_stages=path1_stages,
            path2_stages=path2_stages
        )

    return sessions


def analyze_latency(tx_file: str, rx_file: str):
    """分析延迟分布"""

    print(f"Loading TX log: {tx_file}")
    tx_sessions = parse_log_file(tx_file)
    print(f"  Found {len(tx_sessions)} TX sessions")

    print(f"Loading RX log: {rx_file}")
    rx_sessions = parse_log_file(rx_file)
    print(f"  Found {len(rx_sessions)} RX sessions")

    # 构建结果表
    results = []

    for seq, tx in sorted(tx_sessions.items(), key=lambda x: x[1].total_rtt, reverse=True):
        rx = rx_sessions.get(seq)

        # 计算物理网络延迟
        if rx:
            # TX Inter-Path = 物理网络(双向) + RX处理时间
            # 物理网络延迟 = TX Inter-Path - RX Total RTT
            physical_net = tx.inter_path - rx.total_rtt
            rx_rtt_str = f"{rx.total_rtt:.1f}"
            physical_str = f"{physical_net:.1f}"
            rx_status = "matched"
        else:
            # RX 没有记录，说明 RX 端延迟低于阈值
            physical_net = tx.inter_path  # 近似等于物理网络延迟
            rx_rtt_str = "<threshold"
            physical_str = f"~{physical_net:.1f}"
            rx_status = "no_rx"

        results.append({
            'seq': seq,
            'timestamp': tx.timestamp,
            'tx_path1': tx.path1_total,
            'tx_path2': tx.path2_total,
            'tx_rtt': tx.total_rtt,
            'tx_inter_path': tx.inter_path,
            'rx_rtt': rx_rtt_str,
            'physical_net': physical_str,
            'physical_net_val': physical_net if rx else tx.inter_path,
            'rx_status': rx_status,
            'rx_data': rx
        })

    return results, tx_sessions, rx_sessions


def print_summary_table(results: list, threshold_ms: float = 10.0):
    """打印延迟分段汇总表"""

    threshold_us = threshold_ms * 1000
    high_latency = [r for r in results if r['tx_rtt'] >= threshold_us]

    print("\n" + "=" * 140)
    print(f"高延迟包延迟分段汇总表 (Total RTT >= {threshold_ms}ms)")
    print("=" * 140)

    # 表头
    header = f"{'Seq':>8} | {'Timestamp':^23} | {'TX_Path1':>10} | {'TX_Path2':>10} | {'TX_RTT':>12} | {'TX_InterPath':>12} | {'RX_RTT':>12} | {'PhysNet':>12} | {'Status':>10}"
    print(header)
    print("-" * 140)

    # 数据行
    matched_count = 0
    no_rx_count = 0

    for r in high_latency:
        row = f"{r['seq']:>8} | {r['timestamp']:^23} | {r['tx_path1']:>9.1f}us | {r['tx_path2']:>9.1f}us | {r['tx_rtt']/1000:>10.2f}ms | {r['tx_inter_path']/1000:>10.2f}ms | {r['rx_rtt']:>12} | {r['physical_net']:>12} | {r['rx_status']:>10}"
        print(row)

        if r['rx_status'] == 'matched':
            matched_count += 1
        else:
            no_rx_count += 1

    print("-" * 140)
    print(f"Total: {len(high_latency)} high-latency sessions | Matched with RX: {matched_count} | No RX data: {no_rx_count}")
    print()

    # 延迟来源统计
    print("\n" + "=" * 80)
    print("延迟来源分析")
    print("=" * 80)

    # 分类统计
    physical_dominant = []  # 物理网络为主
    rx_dominant = []        # RX处理为主
    mixed = []              # 混合

    for r in high_latency:
        if r['rx_status'] == 'no_rx':
            physical_dominant.append(r)
        else:
            rx_data = r['rx_data']
            physical_net = r['physical_net_val']
            rx_rtt = rx_data.total_rtt

            if physical_net > rx_rtt * 2:
                physical_dominant.append(r)
            elif rx_rtt > physical_net * 2:
                rx_dominant.append(r)
            else:
                mixed.append(r)

    print(f"\n物理网络延迟为主: {len(physical_dominant)} sessions ({100*len(physical_dominant)/max(1,len(high_latency)):.1f}%)")
    print(f"RX端处理延迟为主: {len(rx_dominant)} sessions ({100*len(rx_dominant)/max(1,len(high_latency)):.1f}%)")
    print(f"混合延迟: {len(mixed)} sessions ({100*len(mixed)/max(1,len(high_latency)):.1f}%)")

    # 详细统计
    if high_latency:
        print("\n--- 延迟统计 (高延迟包) ---")
        tx_rtts = [r['tx_rtt'] for r in high_latency]
        tx_inter_paths = [r['tx_inter_path'] for r in high_latency]
        physical_nets = [r['physical_net_val'] for r in high_latency]

        print(f"TX Total RTT:     avg={sum(tx_rtts)/len(tx_rtts)/1000:.2f}ms, max={max(tx_rtts)/1000:.2f}ms, min={min(tx_rtts)/1000:.2f}ms")
        print(f"TX Inter-Path:    avg={sum(tx_inter_paths)/len(tx_inter_paths)/1000:.2f}ms, max={max(tx_inter_paths)/1000:.2f}ms")
        print(f"Physical Network: avg={sum(physical_nets)/len(physical_nets)/1000:.2f}ms, max={max(physical_nets)/1000:.2f}ms")

        matched_results = [r for r in high_latency if r['rx_status'] == 'matched']
        if matched_results:
            rx_rtts = [r['rx_data'].total_rtt for r in matched_results]
            print(f"RX Total RTT:     avg={sum(rx_rtts)/len(rx_rtts)/1000:.2f}ms, max={max(rx_rtts)/1000:.2f}ms (matched only)")


def print_inter_path_distribution(results: list):
    """打印 Inter-Path Latency 分布"""

    print("\n" + "=" * 80)
    print("Inter-Path Latency 分布统计")
    print("=" * 80)

    inter_paths = [r['tx_inter_path'] for r in results]

    if not inter_paths:
        print("No data")
        return

    # 分区间统计
    buckets = [
        (0, 100, "0-100us"),
        (100, 1000, "100us-1ms"),
        (1000, 10000, "1-10ms"),
        (10000, 50000, "10-50ms"),
        (50000, 100000, "50-100ms"),
        (100000, float('inf'), ">100ms"),
    ]

    for low, high, label in buckets:
        count = sum(1 for v in inter_paths if low <= v < high)
        pct = 100 * count / len(inter_paths)
        bar = "#" * int(pct / 2)
        print(f"  {label:>12}: {count:>6} ({pct:>5.1f}%) {bar}")

    print(f"\n  Total: {len(inter_paths)} sessions")
    print(f"  Mean:  {sum(inter_paths)/len(inter_paths)/1000:.2f} ms")
    print(f"  Max:   {max(inter_paths)/1000:.2f} ms")
    print(f"  Min:   {min(inter_paths)/1000:.2f} ms")


def export_csv(results: list, output_file: str, stat_threshold_ms: float = 10.0):
    """导出 CSV 文件，包含延迟分段数据和统计"""

    stat_threshold_us = stat_threshold_ms * 1000
    total_rows = len(results)

    # 统计每列超过阈值的数量
    count_path1 = 0
    count_path2 = 0
    count_physical = 0
    count_rx = 0
    count_rtt = 0
    rx_valid_count = 0

    rows = []
    for r in results:
        tx_rtt = r['tx_rtt']
        tx_path1 = r['tx_path1']
        tx_path2 = r['tx_path2']
        physical_net = r['physical_net_val']
        rx_rtt = r['rx_data'].total_rtt if r['rx_data'] else 0

        # 统计
        if tx_path1 > stat_threshold_us:
            count_path1 += 1
        if tx_path2 > stat_threshold_us:
            count_path2 += 1
        if physical_net > stat_threshold_us:
            count_physical += 1
        if r['rx_data'] and rx_rtt > stat_threshold_us:
            count_rx += 1
        if r['rx_data']:
            rx_valid_count += 1
        if tx_rtt > stat_threshold_us:
            count_rtt += 1

        # 计算比例
        path1_pct = (tx_path1 / tx_rtt * 100) if tx_rtt > 0 else 0
        path2_pct = (tx_path2 / tx_rtt * 100) if tx_rtt > 0 else 0
        physical_pct = (physical_net / tx_rtt * 100) if tx_rtt > 0 else 0
        rx_pct = (rx_rtt / tx_rtt * 100) if tx_rtt > 0 else 0

        rows.append([
            r['seq'],
            r['timestamp'],
            f"{tx_path1:.1f}",
            f"{path1_pct:.2f}%",
            f"{tx_path2:.1f}",
            f"{path2_pct:.2f}%",
            f"{physical_net:.1f}",
            f"{physical_pct:.2f}%",
            f"{rx_rtt:.1f}" if r['rx_data'] else '-',
            f"{rx_pct:.2f}%" if r['rx_data'] else '-',
            f"{tx_rtt:.1f}",
            r['rx_status']
        ])

    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        # 表头
        writer.writerow([
            'Seq', 'Timestamp',
            'TX_Path1_us', 'TX_Path1_%',
            'TX_Path2_us', 'TX_Path2_%',
            'Physical_Net_us', 'Physical_Net_%',
            'RX_RTT_us', 'RX_RTT_%',
            'TX_RTT_us',
            'RX_Status'
        ])

        # 数据行
        for row in rows:
            writer.writerow(row)

        # 空行分隔
        writer.writerow([])

        # 统计行1: 超过阈值的数量
        writer.writerow([
            f'>{stat_threshold_ms:.0f}ms Count', '',
            count_path1, '',
            count_path2, '',
            count_physical, '',
            f'{count_rx} (of {rx_valid_count})', '',
            count_rtt,
            f'Total: {total_rows}'
        ])

        # 统计行2: 占比
        writer.writerow([
            f'>{stat_threshold_ms:.0f}ms Ratio', '',
            f'{count_path1/total_rows*100:.2f}%' if total_rows > 0 else '-', '',
            f'{count_path2/total_rows*100:.2f}%' if total_rows > 0 else '-', '',
            f'{count_physical/total_rows*100:.2f}%' if total_rows > 0 else '-', '',
            f'{count_rx/rx_valid_count*100:.2f}%' if rx_valid_count > 0 else '-', '',
            f'{count_rtt/total_rows*100:.2f}%' if total_rows > 0 else '-',
            ''
        ])

    print(f"\nCSV saved: {output_file}")
    print(f"Total rows: {total_rows}")
    print(f"\n>{stat_threshold_ms:.0f}ms Statistics:")
    print(f"  TX_Path1:     {count_path1}/{total_rows} ({count_path1/total_rows*100:.2f}%)" if total_rows > 0 else "  TX_Path1: N/A")
    print(f"  TX_Path2:     {count_path2}/{total_rows} ({count_path2/total_rows*100:.2f}%)" if total_rows > 0 else "  TX_Path2: N/A")
    print(f"  Physical_Net: {count_physical}/{total_rows} ({count_physical/total_rows*100:.2f}%)" if total_rows > 0 else "  Physical_Net: N/A")
    print(f"  RX_RTT:       {count_rx}/{rx_valid_count} ({count_rx/rx_valid_count*100:.2f}%)" if rx_valid_count > 0 else "  RX_RTT: N/A")
    print(f"  TX_RTT:       {count_rtt}/{total_rows} ({count_rtt/total_rows*100:.2f}%)" if total_rows > 0 else "  TX_RTT: N/A")


def main():
    parser = argparse.ArgumentParser(
        description='Inter-Path Latency Analyzer - 分析TX/RX日志的延迟分布',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python3 interpath_latency_analyzer.py --tx tx.log --rx rx.log --csv result.csv
  python3 interpath_latency_analyzer.py --tx tx.log --rx rx.log --csv result.csv --stat-threshold 5
        '''
    )
    parser.add_argument('--tx', required=True, help='TX log file (发送方向日志)')
    parser.add_argument('--rx', required=True, help='RX log file (接收方向日志)')
    parser.add_argument('--csv', required=True, help='Output CSV file (输出CSV文件)')
    parser.add_argument('--stat-threshold', type=float, default=10.0,
                        help='统计阈值(ms)，统计各列延迟超过此值的数量 (default: 10)')
    parser.add_argument('--json', help='Optional: 同时输出JSON格式详细结果')
    parser.add_argument('--quiet', action='store_true', help='安静模式，不打印控制台汇总')

    args = parser.parse_args()

    results, tx_sessions, rx_sessions = analyze_latency(args.tx, args.rx)

    # 导出 CSV
    export_csv(results, args.csv, args.stat_threshold)

    # 打印控制台汇总
    if not args.quiet:
        print_summary_table(results, args.stat_threshold)
        print_inter_path_distribution(results)

    # 保存 JSON 详细结果
    if args.json:
        output_data = {
            'stat_threshold_ms': args.stat_threshold,
            'total_tx_sessions': len(tx_sessions),
            'total_rx_sessions': len(rx_sessions),
            'results': [
                {
                    'seq': r['seq'],
                    'timestamp': r['timestamp'],
                    'tx_path1_us': r['tx_path1'],
                    'tx_path2_us': r['tx_path2'],
                    'tx_rtt_us': r['tx_rtt'],
                    'tx_inter_path_us': r['tx_inter_path'],
                    'rx_rtt_us': r['rx_data'].total_rtt if r['rx_data'] else None,
                    'physical_net_us': r['physical_net_val'],
                    'rx_status': r['rx_status']
                }
                for r in results
            ]
        }
        with open(args.json, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nJSON saved: {args.json}")


if __name__ == '__main__':
    main()
