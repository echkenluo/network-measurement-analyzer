#!/usr/bin/env python3
"""
基于完整分析报告生成总的Summary Report
"""

import re
import json
from collections import defaultdict
from datetime import datetime

def parse_report_file(report_file):
    """解析完整的分析报告"""
    
    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取汇总统计部分
    summary_pattern = r'===== 汇总统计 =====(.*?)===== .*? 每日分析报告 ====='
    summary_match = re.search(summary_pattern, content, re.DOTALL)
    
    summary_stats = {}
    if summary_match:
        summary_content = summary_match.group(1)
        
        # 解析存储网络统计
        storage_pattern = r'=== 存储网络.*?总体统计 ===(.*?)=== 管理网络'
        storage_match = re.search(storage_pattern, summary_content, re.DOTALL)
        if storage_match:
            storage_content = storage_match.group(1)
            summary_stats['storage'] = parse_network_stats(storage_content)
        
        # 解析管理网络统计
        mgmt_pattern = r'=== 管理网络.*?总体统计 ===(.*?)$'
        mgmt_match = re.search(mgmt_pattern, summary_content, re.DOTALL)
        if mgmt_match:
            mgmt_content = mgmt_match.group(1)
            summary_stats['management'] = parse_network_stats(mgmt_content)
    
    # 解析每日矩阵数据来获取更详细的统计
    daily_stats = parse_daily_matrices(content)
    
    return summary_stats, daily_stats

def parse_network_stats(content):
    """解析网络统计内容"""
    stats = {}
    
    patterns = {
        'total_days': r'总天数: (\d+)',
        'valid_pairs': r'有效IP对数据: ([\d,]+)',
        'theoretical_packets': r'理论总包数: ([\d,]+)',
        'actual_lost': r'实际丢包数: ([\d,]+)',
        'actual_latency': r'实际高延迟数: ([\d,]+)',
        'loss_rate': r'总体丢包率: ([\d.]+)%',
        'latency_rate': r'总体高延迟率: ([\d.]+)%',
        'ips': r'包含IP: (.*?)$'
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            value = match.group(1).replace(',', '') if key not in ['loss_rate', 'latency_rate', 'ips'] else match.group(1)
            if key in ['total_days', 'valid_pairs', 'theoretical_packets', 'actual_lost', 'actual_latency']:
                stats[key] = int(value)
            elif key in ['loss_rate', 'latency_rate']:
                stats[key] = float(value)
            else:
                stats[key] = value
    
    return stats

def parse_daily_matrices(content):
    """解析每日矩阵数据"""
    daily_stats = {
        'storage': defaultdict(lambda: {'total_loss': 0, 'total_latency': 0, 'worst_connections': []}),
        'management': defaultdict(lambda: {'total_loss': 0, 'total_latency': 0, 'worst_connections': []})
    }
    
    # 查找所有日期的丢包数量矩阵
    date_pattern = r'=== (\d{4}-\d{2}-\d{2}) - (存储网络|管理网络).*?【丢包数量矩阵】(.*?)================'
    
    for match in re.finditer(date_pattern, content, re.DOTALL):
        date = match.group(1)
        network_type = 'storage' if '存储网络' in match.group(2) else 'management'
        matrix_content = match.group(3)
        
        # 解析矩阵中的数值
        lines = matrix_content.strip().split('\n')[2:]  # 跳过标题行
        total_daily_loss = 0
        connections = []
        
        for line in lines:
            if line.strip() and not line.startswith('-'):
                parts = line.split()
                if len(parts) > 1:
                    source_ip = parts[0]
                    for i, value in enumerate(parts[1:], 1):
                        if value != 'N/A' and value.replace(',', '').isdigit():
                            loss_count = int(value.replace(',', ''))
                            total_daily_loss += loss_count
                            if loss_count > 1000:  # 记录严重丢包连接
                                target_idx = i - 1
                                connections.append({
                                    'source': source_ip,
                                    'loss_count': loss_count,
                                    'target_idx': target_idx
                                })
        
        daily_stats[network_type][date]['total_loss'] = total_daily_loss
        daily_stats[network_type][date]['worst_connections'] = sorted(connections, 
                                                                    key=lambda x: x['loss_count'], 
                                                                    reverse=True)[:5]
    
    return daily_stats

def generate_summary_report(summary_stats, daily_stats):
    """生成总的Summary Report"""
    
    report_lines = []
    report_lines.append("# 集群网络监控分析总结报告")
    report_lines.append("")
    report_lines.append("## 📊 整体网络质量评估")
    report_lines.append("")
    
    # 总体对比表格
    report_lines.append("| 网络类型 | 覆盖天数 | 有效连接对 | 总体丢包率 | 总体高延迟率 | 网络质量评级 |")
    report_lines.append("|---------|----------|------------|------------|-------------|------------|")
    
    for net_type in ['storage', 'management']:
        if net_type in summary_stats:
            stats = summary_stats[net_type]
            network_name = "存储网络" if net_type == 'storage' else "管理网络"
            
            # 计算网络质量评级
            loss_rate = stats['loss_rate']
            latency_rate = stats['latency_rate']
            
            if loss_rate < 0.01 and latency_rate < 0.002:
                quality = "优秀 ⭐⭐⭐"
            elif loss_rate < 0.05 and latency_rate < 0.01:
                quality = "良好 ⭐⭐"
            elif loss_rate < 0.1 and latency_rate < 0.05:
                quality = "一般 ⭐"
            else:
                quality = "需改进 ⚠️"
            
            report_lines.append(f"| {network_name} | {stats['total_days']}天 | {stats['valid_pairs']:,}对 | {stats['loss_rate']:.4f}% | {stats['latency_rate']:.4f}% | {quality} |")
    
    report_lines.append("")
    report_lines.append("## 🔍 关键发现")
    report_lines.append("")
    
    # 比较两个网络
    if 'storage' in summary_stats and 'management' in summary_stats:
        storage_loss = summary_stats['storage']['loss_rate']
        mgmt_loss = summary_stats['management']['loss_rate']
        storage_latency = summary_stats['storage']['latency_rate']
        mgmt_latency = summary_stats['management']['latency_rate']
        
        report_lines.append("### 网络类型对比")
        report_lines.append("")
        
        if storage_loss > mgmt_loss:
            diff = storage_loss - mgmt_loss
            report_lines.append(f"- **存储网络丢包率较高**: 比管理网络高 {diff:.4f}%")
        else:
            diff = mgmt_loss - storage_loss
            report_lines.append(f"- **管理网络丢包率较高**: 比存储网络高 {diff:.4f}%")
        
        if storage_latency > mgmt_latency:
            diff = storage_latency - mgmt_latency
            report_lines.append(f"- **存储网络延迟问题较多**: 比管理网络高 {diff:.4f}%")
        else:
            diff = mgmt_latency - storage_latency
            report_lines.append(f"- **管理网络延迟问题较多**: 比存储网络高 {diff:.4f}%")
    
    report_lines.append("")
    
    # 分析最严重的问题日期
    report_lines.append("## 🚨 问题热点分析")
    report_lines.append("")
    
    for net_type in ['storage', 'management']:
        if net_type in daily_stats:
            network_name = "存储网络" if net_type == 'storage' else "管理网络"
            report_lines.append(f"### {network_name}问题热点")
            report_lines.append("")
            
            # 找出丢包最严重的日期
            worst_days = sorted(daily_stats[net_type].items(), 
                              key=lambda x: x[1]['total_loss'], 
                              reverse=True)[:5]
            
            if worst_days:
                report_lines.append("**丢包最严重的日期**:")
                report_lines.append("")
                for i, (date, stats) in enumerate(worst_days, 1):
                    total_loss = stats['total_loss']
                    if total_loss > 0:
                        report_lines.append(f"{i}. **{date}**: 总丢包 {total_loss:,} 个")
                        if stats['worst_connections']:
                            worst_conn = stats['worst_connections'][0]
                            report_lines.append(f"   - 最严重连接: {worst_conn['source']} 丢包 {worst_conn['loss_count']:,} 个")
                report_lines.append("")
    
    # 数据完整性验证
    report_lines.append("## ✅ 数据完整性")
    report_lines.append("")
    
    for net_type in ['storage', 'management']:
        if net_type in summary_stats:
            stats = summary_stats[net_type]
            network_name = "存储网络" if net_type == 'storage' else "管理网络"
            
            # 计算理论和实际的一致性
            expected_daily_packets = 576000
            actual_avg_daily_packets = stats['theoretical_packets'] / stats['valid_pairs']
            
            report_lines.append(f"### {network_name}")
            report_lines.append(f"- 理论每日发包量: 576,000包/IP对")
            report_lines.append(f"- 实际平均: {actual_avg_daily_packets:,.0f}包/IP对")
            report_lines.append(f"- 数据完整性: {'✅ 正常' if abs(actual_avg_daily_packets - expected_daily_packets) < 1000 else '⚠️ 异常'}")
            report_lines.append("")
    
    # 趋势分析
    report_lines.append("## 📈 网络趋势分析")
    report_lines.append("")
    
    # 分析时间趋势（基于日期）
    all_dates = set()
    for net_type in daily_stats:
        all_dates.update(daily_stats[net_type].keys())
    
    sorted_dates = sorted(list(all_dates))
    if len(sorted_dates) >= 3:
        early_dates = sorted_dates[:len(sorted_dates)//3]
        late_dates = sorted_dates[-len(sorted_dates)//3:]
        
        for net_type in ['storage', 'management']:
            if net_type in daily_stats:
                network_name = "存储网络" if net_type == 'storage' else "管理网络"
                
                early_loss = sum(daily_stats[net_type][date]['total_loss'] 
                               for date in early_dates 
                               if date in daily_stats[net_type])
                late_loss = sum(daily_stats[net_type][date]['total_loss'] 
                              for date in late_dates 
                              if date in daily_stats[net_type])
                
                if early_loss > 0 and late_loss > 0:
                    trend = "改善" if late_loss < early_loss else "恶化" if late_loss > early_loss else "稳定"
                    report_lines.append(f"- **{network_name}**: 网络质量总体呈 **{trend}** 趋势")
    
    report_lines.append("")
    report_lines.append("## 🎯 建议")
    report_lines.append("")
    report_lines.append("1. **持续监控**: 保持对网络质量的持续监控")
    report_lines.append("2. **问题预警**: 建议设置丢包率>0.1%的告警阈值")
    report_lines.append("3. **重点关注**: 对识别出的问题节点进行重点监控")
    report_lines.append("4. **定期分析**: 建议每周进行网络质量分析")
    
    return '\n'.join(report_lines)

def main():
    """主函数"""
    report_file = 'corrected_network_analysis_report.txt'
    output_file = 'network_summary_report.md'
    
    print("正在解析完整分析报告...")
    summary_stats, daily_stats = parse_report_file(report_file)
    
    print("正在生成总结报告...")
    summary_report = generate_summary_report(summary_stats, daily_stats)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(summary_report)
    
    print(f"总结报告已保存到 {output_file}")
    
    # 显示部分内容
    print("\n" + "="*50)
    print("总结报告预览:")
    print("="*50)
    lines = summary_report.split('\n')
    for line in lines[:30]:  # 显示前30行
        print(line)
    if len(lines) > 30:
        print("...")

if __name__ == "__main__":
    main() 