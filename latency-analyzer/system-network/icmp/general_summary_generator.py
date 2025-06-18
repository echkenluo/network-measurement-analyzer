#!/usr/bin/env python3
"""
通用延迟分析Summary生成器
分析通用延迟分析器生成的数据，生成延迟分布和stage分布报告
"""

import json
import statistics
from collections import defaultdict, Counter

class GeneralSummaryGenerator:
    def __init__(self, analysis_file):
        self.analysis_file = analysis_file
        self.data = None
        
    def load_data(self):
        """加载分析数据"""
        with open(self.analysis_file, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        print(f"已加载分析数据: {self.analysis_file}")
        
    def get_latency_range_label(self, latency_us):
        """将延迟(us)分类到合适的区间"""
        latency_ms = latency_us / 1000  # 转换为毫秒
        
        if latency_ms < 10:
            return "0-10ms"
        elif latency_ms < 100:
            return "10-100ms"
        elif latency_ms < 500:
            return "100-500ms"
        elif latency_ms < 1000:
            return "500-1000ms"
        elif latency_ms < 3000:
            return "1000-3000ms"
        elif latency_ms < 60000:
            return "3000-60000ms"
        else:
            return ">60000ms"
    
    def get_range_order(self):
        """获取区间的显示顺序"""
        return [
            "0-10ms",
            "10-100ms",
            "100-500ms",
            "500-1000ms", 
            "1000-3000ms",
            "3000-60000ms",
            ">60000ms"
        ]
    
    def analyze_sessions(self):
        """分析所有node pairs的session数据"""
        analysis = self.data['analysis']
        valid_sessions = analysis.get('valid_sessions', [])
        dropped_sessions = analysis.get('dropped_sessions', [])
        node_pairs = analysis.get('node_pairs', [])
        
        # 总体分析
        all_max_latencies = []
        valid_stage_distribution = Counter()
        valid_range_distribution = Counter()
        valid_range_distribution_above_10ms = Counter()
        
        # 按node pair分析
        pair_analysis = {}
        
        for session in valid_sessions:
            max_latency = session.get('max_latency', 0)
            pair_name = session.get('pair_name', 'unknown')
            
            # 初始化pair分析
            if pair_name not in pair_analysis:
                pair_analysis[pair_name] = {
                    'latencies': [],
                    'stage_distribution': Counter(),
                    'range_distribution': Counter(),
                    'range_distribution_above_10ms': Counter()
                }
            
            if max_latency > 0:
                all_max_latencies.append(max_latency)
                pair_analysis[pair_name]['latencies'].append(max_latency)
                
                # 分类到延迟区间
                range_label = self.get_latency_range_label(max_latency)
                valid_range_distribution[range_label] += 1
                pair_analysis[pair_name]['range_distribution'][range_label] += 1
                
                # 只统计10ms以上的延迟分布和stage分布
                latency_ms = max_latency / 1000
                if latency_ms >= 10:
                    valid_range_distribution_above_10ms[range_label] += 1
                    pair_analysis[pair_name]['range_distribution_above_10ms'][range_label] += 1
                    
                    # 统计最大延迟所在的stage (只统计10ms以上)
                    max_stage = session.get('max_stage')
                    if max_stage:
                        valid_stage_distribution[max_stage] += 1
                        pair_analysis[pair_name]['stage_distribution'][max_stage] += 1
        
        # 分析丢包sessions
        dropped_stage_distribution = Counter()
        drop_reason_distribution = Counter()
        
        for session in dropped_sessions:
            # 统计最大延迟所在的stage
            max_stage = session.get('max_stage')
            if max_stage:
                dropped_stage_distribution[max_stage] += 1
            
            # 统计丢包原因
            drop_details = session.get('drop_details', [])
            for reason in drop_details:
                drop_reason_distribution[reason] += 1
        
        # 生成总体统计结果
        summary = {
            'node_pairs': node_pairs,
            'total_sessions': analysis.get('total_sessions', 0),
            'matched_sessions': analysis.get('matched_sessions', 0),
            'outgoing_only': analysis.get('outgoing_only', 0),
            'incoming_only': analysis.get('incoming_only', 0),
            'overall_analysis': {
                'total_valid_sessions': len(valid_sessions),
                'sessions_with_latency': len(all_max_latencies),
                'latency_distribution': dict(valid_range_distribution),
                'latency_distribution_above_10ms': dict(valid_range_distribution_above_10ms),
                'stage_distribution': dict(valid_stage_distribution)
            },
            'dropped_sessions_analysis': {
                'total_dropped_sessions': len(dropped_sessions),
                'stage_distribution': dict(dropped_stage_distribution),
                'drop_reason_distribution': dict(drop_reason_distribution)
            },
            'pair_analysis': {}
        }
        
        # 添加总体延迟统计
        if all_max_latencies:
            summary['overall_analysis']['latency_statistics'] = {
                'count': len(all_max_latencies),
                'mean': statistics.mean(all_max_latencies),
                'median': statistics.median(all_max_latencies),
                'min': min(all_max_latencies),
                'max': max(all_max_latencies),
                'std': statistics.stdev(all_max_latencies) if len(all_max_latencies) > 1 else 0,
                'p95': sorted(all_max_latencies)[int(len(all_max_latencies) * 0.95)] if len(all_max_latencies) > 1 else all_max_latencies[0],
                'p99': sorted(all_max_latencies)[int(len(all_max_latencies) * 0.99)] if len(all_max_latencies) > 1 else all_max_latencies[0]
            }
        
        # 生成每个pair的统计
        for pair_name, pair_data in pair_analysis.items():
            latencies = pair_data['latencies']
            if latencies:
                pair_stats = {
                    'total_sessions': len(latencies),
                    'latency_distribution': dict(pair_data['range_distribution']),
                    'latency_distribution_above_10ms': dict(pair_data['range_distribution_above_10ms']),
                    'stage_distribution': dict(pair_data['stage_distribution']),
                    'latency_statistics': {
                        'count': len(latencies),
                        'mean': statistics.mean(latencies),
                        'median': statistics.median(latencies),
                        'min': min(latencies),
                        'max': max(latencies),
                        'std': statistics.stdev(latencies) if len(latencies) > 1 else 0,
                        'p95': sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0],
                        'p99': sorted(latencies)[int(len(latencies) * 0.99)] if len(latencies) > 1 else latencies[0]
                    }
                }
                summary['pair_analysis'][pair_name] = pair_stats
        
        # 计算百分比
        total_valid = len(all_max_latencies)
        total_dropped = len(dropped_sessions)
        total_above_10ms = sum(valid_range_distribution_above_10ms.values())
        
        if total_valid > 0:
            valid_range_percentages = {}
            valid_stage_percentages = {}
            for range_label, count in valid_range_distribution.items():
                valid_range_percentages[range_label] = (count / total_valid) * 100
            
            # 计算stage百分比 (基于10ms以上的sessions)
            if total_above_10ms > 0:
                for stage, count in valid_stage_distribution.items():
                    valid_stage_percentages[stage] = (count / total_above_10ms) * 100
            
            summary['overall_analysis']['range_percentages'] = valid_range_percentages
            summary['overall_analysis']['stage_percentages'] = valid_stage_percentages
            
            # 计算10ms以上延迟的百分比
            if total_above_10ms > 0:
                valid_range_percentages_above_10ms = {}
                for range_label, count in valid_range_distribution_above_10ms.items():
                    valid_range_percentages_above_10ms[range_label] = (count / total_above_10ms) * 100
                summary['overall_analysis']['range_percentages_above_10ms'] = valid_range_percentages_above_10ms
        
        if total_dropped > 0:
            dropped_stage_percentages = {}
            drop_reason_percentages = {}
            for stage, count in dropped_stage_distribution.items():
                dropped_stage_percentages[stage] = (count / total_dropped) * 100
            for reason, count in drop_reason_distribution.items():
                drop_reason_percentages[reason] = (count / total_dropped) * 100
            summary['dropped_sessions_analysis']['stage_percentages'] = dropped_stage_percentages
            summary['dropped_sessions_analysis']['drop_reason_percentages'] = drop_reason_percentages
        
        return summary
    
    def format_latency(self, latency_us):
        """格式化延迟显示"""
        if latency_us < 1000:
            return f"{latency_us:.1f} us"
        elif latency_us < 1000000:
            return f"{latency_us/1000:.1f} ms"
        else:
            return f"{latency_us/1000000:.1f} s"
    
    def print_summary(self, summary):
        """打印分析结果"""
        print(f"\n{'='*100}")
        print(f"通用网络延迟分析Summary")
        print(f"Node Pairs: {len(summary['node_pairs'])}")
        for pair in summary['node_pairs']:
            print(f"  - {pair['pair_name']}: {pair['src_ip']} -> {pair['dst_ip']}")
        print(f"总Session数: {summary['total_sessions']}")
        print(f"{'='*100}")
        
        # 总体分析
        overall_analysis = summary['overall_analysis']
        print(f"\n🟢 总体分析:")
        print(f"  有效Session数: {overall_analysis['total_valid_sessions']}")
        print(f"  有延迟数据: {overall_analysis['sessions_with_latency']}")
        
        if 'latency_statistics' in overall_analysis:
            stats = overall_analysis['latency_statistics']
            print(f"\n  总体延迟统计 (最大延迟):")
            print(f"    平均值: {self.format_latency(stats['mean'])}")
            print(f"    中位数: {self.format_latency(stats['median'])}")
            print(f"    最小值: {self.format_latency(stats['min'])}")
            print(f"    最大值: {self.format_latency(stats['max'])}")
            print(f"    标准差: {self.format_latency(stats['std'])}")
            print(f"    95%分位: {self.format_latency(stats['p95'])}")
            print(f"    99%分位: {self.format_latency(stats['p99'])}")
        
        # 总体延迟区间分布
        if 'latency_distribution' in overall_analysis:
            print(f"\n  总体延迟区间分布:")
            for range_label in self.get_range_order():
                count = overall_analysis['latency_distribution'].get(range_label, 0)
                if count > 0:
                    percent = overall_analysis.get('range_percentages', {}).get(range_label, 0)
                    print(f"    {range_label}: {count} sessions ({percent:.1f}%)")
        
        # 总体延迟stage分布 (只显示10ms以上)
        if 'stage_distribution' in overall_analysis and overall_analysis['stage_distribution']:
            print(f"\n  总体最大延迟Stage分布 (>=10ms):")
            stage_percentages = overall_analysis.get('stage_percentages', {})
            sorted_stages = sorted(overall_analysis['stage_distribution'].items(), 
                                 key=lambda x: x[1], reverse=True)
            
            for stage, count in sorted_stages:
                percent = stage_percentages.get(stage, 0)
                print(f"    {stage}: {count} sessions ({percent:.1f}%)")
        
        # 按pair详细分析
        print(f"\n📊 各Node Pair详细分析:")
        for pair_name, pair_stats in summary['pair_analysis'].items():
            print(f"\n  📍 {pair_name}:")
            print(f"    有效Sessions: {pair_stats['total_sessions']}")
            
            if 'latency_statistics' in pair_stats:
                stats = pair_stats['latency_statistics']
                print(f"    平均延迟: {self.format_latency(stats['mean'])}")
                print(f"    中位数: {self.format_latency(stats['median'])}")
                print(f"    95%分位: {self.format_latency(stats['p95'])}")
                print(f"    最大延迟: {self.format_latency(stats['max'])}")
            
            # 显示延迟分布（只显示有数据的区间）
            if 'latency_distribution' in pair_stats:
                print(f"    延迟分布:")
                for range_label in self.get_range_order():
                    count = pair_stats['latency_distribution'].get(range_label, 0)
                    if count > 0:
                        percent = (count / pair_stats['total_sessions']) * 100
                        print(f"      {range_label}: {count} ({percent:.1f}%)")
        
        # 丢包sessions分析
        dropped_analysis = summary['dropped_sessions_analysis']
        if dropped_analysis['total_dropped_sessions'] > 0:
            print(f"\n🔴 丢包Session分析:")
            print(f"  丢包Session数: {dropped_analysis['total_dropped_sessions']}")
            
            # 丢包原因分布
            if 'drop_reason_distribution' in dropped_analysis:
                print(f"\n  丢包原因分布:")
                drop_reason_percentages = dropped_analysis.get('drop_reason_percentages', {})
                sorted_reasons = sorted(dropped_analysis['drop_reason_distribution'].items(), 
                                      key=lambda x: x[1], reverse=True)
                
                for reason, count in sorted_reasons:
                    percent = drop_reason_percentages.get(reason, 0)
                    print(f"    {reason}: {count} sessions ({percent:.1f}%)")
        
        print(f"\n{'='*100}")
    
    def save_summary(self, summary, filename):
        """保存summary结果"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\n📁 Summary已保存: {filename}")
    
    def generate_summary(self):
        """生成完整的summary"""
        self.load_data()
        summary = self.analyze_sessions()
        return summary

def main():
    import sys
    if len(sys.argv) != 2:
        print("使用方法: python3 general_summary_generator.py <analysis_file>")
        return 1
    
    analysis_file = sys.argv[1]
    
    # 创建summary生成器
    generator = GeneralSummaryGenerator(analysis_file)
    
    # 生成summary
    summary = generator.generate_summary()
    
    # 打印summary
    generator.print_summary(summary)
    
    # 保存summary
    output_file = analysis_file.replace('_analysis.json', '_latency_summary.json')
    generator.save_summary(summary, output_file)

if __name__ == "__main__":
    main() 