#!/usr/bin/env python3
"""
分析Alert CSV中特定VM的告警时间点，并统计告警前1、2、3分钟内的TX PPS数据
"""

import csv
import statistics
from datetime import datetime, timedelta
import re

def parse_alert_csv(csv_file):
    """解析Alert CSV文件，提取rxx8t和89t6c VM的告警时间"""
    alerts = []
    target_vms = ['rxx8t', '89t6c']
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            message = row['Message']
            trigger_time = row['Trigger time']
            
            # 从消息中提取VM名称
            vm_match = re.search(r'next-cpu\d+mem\d+-(\w+)', message)
            if vm_match:
                vm_suffix = vm_match.group(1)
                if vm_suffix in target_vms:
                    alerts.append({
                        'vm_suffix': vm_suffix,
                        'trigger_time': trigger_time,
                        'message': message,
                        'alert_level': row['Alert level']
                    })
    
    return alerts

def parse_pps_log(log_file):
    """解析PPS日志文件"""
    pps_data = []
    
    with open(log_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) >= 7:
                # 解析时间格式: 2025-06-10 02:09:58 PM
                date_part = parts[0]
                time_part = parts[1]
                am_pm = parts[2]
                device = parts[3]
                
                try:
                    # 构建完整的时间字符串
                    time_str = f"{date_part} {time_part} {am_pm}"
                    timestamp = datetime.strptime(time_str, "%Y-%m-%d %I:%M:%S %p")
                    
                    rx_pps = float(parts[4])  # 第一列是RX PPS
                    tx_pps = float(parts[5])  # 第二列是TX PPS
                    
                    pps_data.append({
                        'timestamp': timestamp,
                        'device': device,
                        'rx_pps': rx_pps,
                        'tx_pps': tx_pps
                    })
                except (ValueError, IndexError) as e:
                    print(f"Error parsing line: {line}, error: {e}")
                    continue
    
    return pps_data

def get_pps_stats_before_alert(pps_data, alert_time, device, minutes):
    """获取告警前指定分钟内的PPS统计数据"""
    alert_datetime = datetime.strptime(alert_time, "%Y-%m-%d %H:%M:%S")
    start_time = alert_datetime - timedelta(minutes=minutes)
    
    # 筛选指定设备和时间范围的数据
    filtered_data = []
    for data_point in pps_data:
        if (data_point['device'] == device and 
            data_point['timestamp'] >= start_time and 
            data_point['timestamp'] < alert_datetime):
            filtered_data.append(data_point['tx_pps'])
    
    if len(filtered_data) == 0:
        return {
            'avg_tx_pps': 0,
            'max_tx_pps': 0,
            'min_tx_pps': 0,
            'data_points': 0
        }
    
    return {
        'avg_tx_pps': statistics.mean(filtered_data),
        'max_tx_pps': max(filtered_data),
        'min_tx_pps': min(filtered_data),
        'data_points': len(filtered_data)
    }

def save_results_to_csv(results, filename):
    """保存结果到CSV文件"""
    if not results:
        return
    
    fieldnames = ['vm_suffix', 'device', 'trigger_time', 'alert_level', 'minutes_before', 
                  'avg_tx_pps', 'max_tx_pps', 'min_tx_pps', 'data_points']
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

def analyze_alerts():
    """主分析函数"""
    print("开始分析Alert数据...")
    
    # 解析Alert CSV
    alerts = parse_alert_csv('tmp/Alert_2025-06-12_13_18_12.csv')
    print(f"找到 {len(alerts)} 个相关告警")
    
    # 解析PPS日志
    print("解析PPS日志数据...")
    pps_data = parse_pps_log('tmp/vnet-tx-rate-with-dates.log')
    print(f"解析了 {len(pps_data)} 个PPS数据点")
    
    # VM后缀到vnet设备的映射
    vm_to_vnet = {
        'rxx8t': 'vnet4',
        '89t6c': 'vnet1'
    }
    
    # 分析结果
    results = []
    
    for alert in alerts:
        vm_suffix = alert['vm_suffix']
        trigger_time = alert['trigger_time']
        device = vm_to_vnet[vm_suffix]
        
        print(f"\n分析告警: VM {vm_suffix} ({device}) 在 {trigger_time}")
        
        # 计算告警前1、2、3分钟的统计数据
        for minutes in [1, 2, 3]:
            stats = get_pps_stats_before_alert(pps_data, trigger_time, device, minutes)
            
            result = {
                'vm_suffix': vm_suffix,
                'device': device,
                'trigger_time': trigger_time,
                'alert_level': alert['alert_level'],
                'minutes_before': minutes,
                'avg_tx_pps': round(stats['avg_tx_pps'], 2),
                'max_tx_pps': round(stats['max_tx_pps'], 2),
                'min_tx_pps': round(stats['min_tx_pps'], 2),
                'data_points': stats['data_points']
            }
            results.append(result)
            
            print(f"  前{minutes}分钟: 平均TX PPS: {result['avg_tx_pps']}, "
                  f"最大: {result['max_tx_pps']}, 最小: {result['min_tx_pps']}, "
                  f"数据点: {result['data_points']}")
    
    # 保存结果到CSV
    save_results_to_csv(results, 'alert_pps_analysis_results.csv')
    print(f"\n分析结果已保存到 alert_pps_analysis_results.csv")
    
    # 显示汇总统计
    print("\n=== 汇总统计 ===")
    for vm in ['rxx8t', '89t6c']:
        vm_results = [r for r in results if r['vm_suffix'] == vm]
        if len(vm_results) > 0:
            device = vm_to_vnet[vm]
            print(f"\nVM {vm} ({device}):")
            print(f"  告警次数: {len(vm_results) // 3}")  # 每个告警有3个时间段
            
            for minutes in [1, 2, 3]:
                minute_data = [r for r in vm_results if r['minutes_before'] == minutes]
                if len(minute_data) > 0:
                    avg_of_avgs = statistics.mean([r['avg_tx_pps'] for r in minute_data])
                    max_of_maxs = max([r['max_tx_pps'] for r in minute_data])
                    min_of_mins = min([r['min_tx_pps'] for r in minute_data])
                    print(f"  前{minutes}分钟统计: 平均TX PPS: {avg_of_avgs:.2f}, "
                          f"最大: {max_of_maxs:.2f}, 最小: {min_of_mins:.2f}")
    
    return results

if __name__ == "__main__":
    results = analyze_alerts() 