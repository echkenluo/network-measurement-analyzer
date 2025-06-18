#!/usr/bin/env python3
"""
Fully corrected network monitoring log analysis script - supports multiple data sources

Fixed issues:
1. Source and target IPs in matrix must be from same network type (storage to storage, management to management)
2. Support for configuration file input
3. Correct network isolation logic
4. Flexible log directory configuration, directly specify complete directory path containing log files
5. Support for multiple data sources: highlatency and network-monitor

Usage:
python3 network_monitor_log_summary.py network_config.json [--source highlatency|network-monitor]

Data source description:
- highlatency: Use network-high-latencies.log file (default)
- network-monitor: Use network-monitor.log* files, automatically filter data containing lost_num

Configuration file format:
{
  "nodes": {
    "/path/to/node1/logs": {
      "storage_ip": "192.168.254.31",
      "management_ip": "10.216.19.31"
    }
  }
}
"""

import os
import re
import json
import sys
import argparse
import glob
from datetime import datetime, timedelta
from collections import defaultdict

# Constants definition
PACKETS_PER_TEST = 100
TESTS_PER_MINUTE = 60 // 15  # 4 tests per minute (every 15 seconds)
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
DAILY_PACKETS_PER_IP_PAIR = PACKETS_PER_TEST * TESTS_PER_MINUTE * MINUTES_PER_HOUR * HOURS_PER_DAY
# = 100 * 4 * 60 * 24 = 576,000

def parse_log_entry(line):
    """Parse log entry"""
    pattern = r'\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d+: INFO\] (.+)'
    match = re.match(pattern, line.strip())
    
    if not match:
        return None
    
    date_str = match.group(1)
    time_str = match.group(2)
    data_str = match.group(3)
    
    try:
        data = eval(data_str)
        
        return {
            'date': date_str,
            'time': time_str,
            'ip': data['ip'],
            'latencies_over_threshold': data.get('latencies_over_threshold_in_ms', []),
            'packet_lost_num': data.get('packet_lost_num', 0)
        }
    except:
        return None

def find_network_monitor_files(log_dir):
    """Find all network-monitor.log* files"""
    pattern = os.path.join(log_dir, "network-monitor.log*")
    files = glob.glob(pattern)
    return sorted(files)

def read_filtered_network_monitor_data(log_files):
    """Read and filter network-monitor data, keep only records containing lost_num"""
    filtered_lines = []
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    # Filter lines containing lost_num
                    if 'lost_num' in line:
                        filtered_lines.append(line)
        except Exception as e:
            print(f"  Warning: Unable to read file {log_file}: {e}")
    
    return filtered_lines

def load_config(config_file):
    """Load configuration file"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"Error: Unable to load configuration file {config_file}: {e}")
        sys.exit(1)

def get_network_ips(config):
    """Extract network IP lists from configuration"""
    storage_ips = []
    management_ips = []
    
    for node_config in config['nodes'].values():
        storage_ips.append(node_config['storage_ip'])
        management_ips.append(node_config['management_ip'])
    
    return {
        'storage': sorted(storage_ips),
        'management': sorted(management_ips)
    }

def get_source_ip_for_node(log_dir, config):
    """Get source IP for node based on log directory"""
    if log_dir in config['nodes']:
        return {
            'storage': config['nodes'][log_dir]['storage_ip'],
            'management': config['nodes'][log_dir]['management_ip']
        }
    return None

def classify_ip_and_validate(ip, network_ips):
    """Determine which network type the IP belongs to"""
    if ip in network_ips['storage']:
        return 'storage'
    elif ip in network_ips['management']:
        return 'management'
    else:
        return 'unknown'

def analyze_network_logs(config, data_source='highlatency'):
    """Analyze network logs"""
    
    network_ips = get_network_ips(config)
    print(f"Storage network IPs: {network_ips['storage']}")
    print(f"Management network IPs: {network_ips['management']}")
    print(f"Data source: {data_source}")
    
    # Data structure: {network_type: {date: {source_ip: {target_ip: {'packet_lost': total, 'high_latency': total, 'has_data': bool}}}}}
    network_stats = {
        'storage': defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'packet_lost': 0, 'high_latency': 0, 'has_data': False}))),
        'management': defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'packet_lost': 0, 'high_latency': 0, 'has_data': False})))
    }
    
    for log_dir, node_config in config['nodes'].items():
        print(f"Processing node: {log_dir}")
        print(f"  Storage IP: {node_config['storage_ip']}, Management IP: {node_config['management_ip']}")
        
        if not os.path.exists(log_dir):
            print(f"  Warning: Directory does not exist {log_dir}")
            continue
        
        # Get source IPs for this node
        source_ips = get_source_ip_for_node(log_dir, config)
        if not source_ips:
            print(f"  Error: Unable to get IP configuration for node {log_dir}")
            continue
        
        # Choose different processing methods based on data source
        if data_source == 'highlatency':
            # Original logic: process network-high-latencies.log
            high_latency_file = os.path.join(log_dir, "network-high-latencies.log")
            
            if os.path.exists(high_latency_file):
                try:
                    with open(high_latency_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            entry = parse_log_entry(line)
                            if entry:
                                date = entry['date']
                                target_ip = entry['ip']
                                packet_lost = entry['packet_lost_num']
                                latencies = entry['latencies_over_threshold']
                                
                                # Determine target IP network type
                                network_type = classify_ip_and_validate(target_ip, network_ips)
                                if network_type != 'unknown':
                                    # Get corresponding source IP
                                    source_ip = source_ips[network_type]
                                    
                                    # Store data: source IP -> target IP
                                    network_stats[network_type][date][source_ip][target_ip]['has_data'] = True
                                    network_stats[network_type][date][source_ip][target_ip]['packet_lost'] += packet_lost
                                    
                                    if latencies:
                                        network_stats[network_type][date][source_ip][target_ip]['high_latency'] += len(latencies)
                                
                except Exception as e:
                    print(f"  Error: Unable to process file {high_latency_file}: {e}")
            else:
                print(f"  Warning: File does not exist {high_latency_file}")
        
        elif data_source == 'network-monitor':
            # New logic: process network-monitor.log* files
            monitor_files = find_network_monitor_files(log_dir)
            
            if monitor_files:
                print(f"  Found {len(monitor_files)} network-monitor.log* files")
                
                try:
                    # Read and filter data
                    filtered_lines = read_filtered_network_monitor_data(monitor_files)
                    print(f"  Filtered {len(filtered_lines)} records containing lost_num")
                    
                    # Process filtered data
                    for line in filtered_lines:
                        entry = parse_log_entry(line)
                        if entry:
                            date = entry['date']
                            target_ip = entry['ip']
                            packet_lost = entry['packet_lost_num']
                            latencies = entry['latencies_over_threshold']
                            
                            # Determine target IP network type
                            network_type = classify_ip_and_validate(target_ip, network_ips)
                            if network_type != 'unknown':
                                # Get corresponding source IP
                                source_ip = source_ips[network_type]
                                
                                # Store data: source IP -> target IP
                                network_stats[network_type][date][source_ip][target_ip]['has_data'] = True
                                network_stats[network_type][date][source_ip][target_ip]['packet_lost'] += packet_lost
                                
                                if latencies:
                                    network_stats[network_type][date][source_ip][target_ip]['high_latency'] += len(latencies)
                
                except Exception as e:
                    print(f"  Error: Unable to process network-monitor.log* files: {e}")
            else:
                print(f"  Warning: No network-monitor.log* files found in {log_dir}")
    
    return network_stats

def generate_daily_matrix_report(network_stats, network_type, network_ips):
    """Generate daily matrix report for specified network type"""
    
    if network_type not in network_stats:
        return "No data"
    
    stats = network_stats[network_type]
    report_lines = []
    
    network_name = "Storage Network(192.168.254.x)" if network_type == 'storage' else "Management Network(10.216.19.x)"
    report_lines.append(f"===== {network_name} Daily Analysis Report =====\n")
    
    # Get all dates
    all_dates = sorted(stats.keys())
    if not all_dates:
        return f"{network_name}: No data"
    
    report_lines.append(f"Data coverage period: {all_dates[0]} to {all_dates[-1]} (total {len(all_dates)} days)")
    report_lines.append(f"Theoretical daily packets per IP pair: {DAILY_PACKETS_PER_IP_PAIR:,} packets\n")
    
    # Get all IPs for this network type (as both source and target IPs)
    all_ips = network_ips[network_type]
    
    report_lines.append(f"Network type: {network_name}")
    report_lines.append(f"Included IPs: {', '.join(all_ips)}\n")
    
    # Generate matrix report for each day
    for date in all_dates:
        if date not in stats:
            continue
            
        date_data = stats[date]
        
        report_lines.append(f"=== {date} - {network_name} ===")
        
        # Packet loss rate matrix
        report_lines.append(f"\n[Packet Loss Rate Matrix]")
        header = "Source IP\\Target IP".ljust(18) + " ".join([ip.ljust(16) for ip in all_ips])
        report_lines.append(header)
        report_lines.append("-" * len(header))
        
        for source_ip in all_ips:
            row = [source_ip.ljust(18)]
            for target_ip in all_ips:
                if source_ip == target_ip:
                    # Self ping, mark as N/A
                    row.append("N/A".ljust(16))
                elif (source_ip in date_data and 
                      target_ip in date_data[source_ip] and 
                      date_data[source_ip][target_ip]['has_data']):
                    packet_lost = date_data[source_ip][target_ip]['packet_lost']
                    loss_rate = (packet_lost / DAILY_PACKETS_PER_IP_PAIR) * 100
                    row.append(f"{loss_rate:.4f}%".ljust(16))
                else:
                    row.append("N/A".ljust(16))
            report_lines.append("".join(row))
        
        # High latency rate matrix
        report_lines.append(f"\n[High Latency Rate Matrix]")
        header = "Source IP\\Target IP".ljust(18) + " ".join([ip.ljust(16) for ip in all_ips])
        report_lines.append(header)
        report_lines.append("-" * len(header))
        
        for source_ip in all_ips:
            row = [source_ip.ljust(18)]
            for target_ip in all_ips:
                if source_ip == target_ip:
                    row.append("N/A".ljust(16))
                elif (source_ip in date_data and 
                      target_ip in date_data[source_ip] and 
                      date_data[source_ip][target_ip]['has_data']):
                    high_latency = date_data[source_ip][target_ip]['high_latency']
                    latency_rate = (high_latency / DAILY_PACKETS_PER_IP_PAIR) * 100
                    row.append(f"{latency_rate:.4f}%".ljust(16))
                else:
                    row.append("N/A".ljust(16))
            report_lines.append("".join(row))
        
        # Packet loss count matrix
        report_lines.append(f"\n[Packet Loss Count Matrix]")
        header = "Source IP\\Target IP".ljust(18) + " ".join([ip.ljust(16) for ip in all_ips])
        report_lines.append(header)
        report_lines.append("-" * len(header))
        
        for source_ip in all_ips:
            row = [source_ip.ljust(18)]
            for target_ip in all_ips:
                if source_ip == target_ip:
                    row.append("N/A".ljust(16))
                elif (source_ip in date_data and 
                      target_ip in date_data[source_ip] and 
                      date_data[source_ip][target_ip]['has_data']):
                    packet_lost = date_data[source_ip][target_ip]['packet_lost']
                    row.append(f"{packet_lost:,}".ljust(16))
                else:
                    row.append("N/A".ljust(16))
            report_lines.append("".join(row))
        
        report_lines.append("\n" + "="*80 + "\n")
    
    return '\n'.join(report_lines)

def generate_summary_statistics(network_stats, network_ips):
    """Generate summary statistics"""
    report_lines = []
    report_lines.append("===== Summary Statistics =====\n")
    
    for network_type in ['storage', 'management']:
        network_name = "Storage Network(192.168.254.x)" if network_type == 'storage' else "Management Network(10.216.19.x)"
        
        if network_type not in network_stats or not network_stats[network_type]:
            report_lines.append(f"{network_name}: No data\n")
            continue
        
        stats = network_stats[network_type]
        report_lines.append(f"=== {network_name} Overall Statistics ===")
        
        # Calculate overall statistics
        total_packet_lost = 0
        total_high_latency = 0
        total_valid_pairs = 0
        total_days = len(stats)
        
        for date_data in stats.values():
            for source_data in date_data.values():
                for target_data in source_data.values():
                    if target_data['has_data']:
                        total_packet_lost += target_data['packet_lost']
                        total_high_latency += target_data['high_latency']
                        total_valid_pairs += 1
        
        total_expected_packets = total_valid_pairs * DAILY_PACKETS_PER_IP_PAIR
        
        if total_expected_packets > 0:
            overall_loss_rate = (total_packet_lost / total_expected_packets) * 100
            overall_latency_rate = (total_high_latency / total_expected_packets) * 100
            
            report_lines.append(f"Total days: {total_days}")
            report_lines.append(f"Valid IP pair data: {total_valid_pairs}")
            report_lines.append(f"Theoretical total packets: {total_expected_packets:,}")
            report_lines.append(f"Actual packet loss: {total_packet_lost:,}")
            report_lines.append(f"Actual high latency: {total_high_latency:,}")
            report_lines.append(f"Overall packet loss rate: {overall_loss_rate:.4f}%")
            report_lines.append(f"Overall high latency rate: {overall_latency_rate:.4f}%")
            
            # Show IP list for this network type
            report_lines.append(f"Included IPs: {', '.join(network_ips[network_type])}")
        
        report_lines.append("")
    
    return '\n'.join(report_lines)

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Network monitoring log analysis tool')
    parser.add_argument('config_file', help='Network configuration JSON file path')
    parser.add_argument('-s', '--source', choices=['highlatency', 'network-monitor'], 
                       default='highlatency', help='Data source type (default: highlatency)')
    parser.add_argument('-o', '--output', default='corrected_network_analysis_report.txt', 
                       help='Output report filename (default: corrected_network_analysis_report.txt)')
    
    args = parser.parse_args()
    
    print("Starting fully corrected network monitoring log analysis...")
    print(f"Theoretical daily packet calculation: 100 packets/test × 4 tests/minute × 60 minutes/hour × 24 hours/day = {DAILY_PACKETS_PER_IP_PAIR:,} packets/day")
    print(f"Configuration file: {args.config_file}")
    print(f"Data source: {args.source}")
    
    # Load configuration
    config = load_config(args.config_file)
    
    print("\nNode configuration:")
    for log_dir, node_config in config['nodes'].items():
        print(f"  {log_dir}:")
        print(f"    Storage IP: {node_config['storage_ip']}")
        print(f"    Management IP: {node_config['management_ip']}")
    
    # Get network IP configuration
    network_ips = get_network_ips(config)
    
    # Analyze logs
    network_stats = analyze_network_logs(config, args.source)
    
    print("\nGenerating storage network report...")
    storage_report = generate_daily_matrix_report(network_stats, 'storage', network_ips)
    
    print("Generating management network report...")
    management_report = generate_daily_matrix_report(network_stats, 'management', network_ips)
    
    print("Generating summary statistics...")
    summary_report = generate_summary_statistics(network_stats, network_ips)
    
    # Combine reports
    full_report = summary_report + "\n\n" + storage_report + "\n\n" + management_report
    
    # Generate output filename with data source identifier
    base_name, ext = os.path.splitext(args.output)
    output_file = f"{base_name}_{args.source}{ext}"
    
    # Save report to file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(full_report)
    
    print(f"Fully corrected analysis report saved to {output_file}")
    
    # Display summary section
    print("\n" + "="*50)
    print(summary_report)

if __name__ == "__main__":
    main() 