#!/usr/bin/env python3
"""
General Network Latency Analyzer
Supports ICMP latency data analysis for multiple node pairs, with configuration file and command line input support
"""

import os
import re
import json
import argparse
from collections import defaultdict
from datetime import datetime
import statistics
from pathlib import Path

class GeneralLatencyAnalyzer:
    def __init__(self):
        self.sessions = []
        self.node_pairs = []
        
    def add_node_pair(self, src_ip, dst_ip, outgoing_file, incoming_file, pair_name=None):
        """Add a node pair configuration"""
        if not pair_name:
            pair_name = f"{src_ip}->{dst_ip}"
            
        self.node_pairs.append({
            'src_ip': src_ip,
            'dst_ip': dst_ip,
            'outgoing_file': outgoing_file,
            'incoming_file': incoming_file,
            'pair_name': pair_name
        })
    
    def parse_session_block(self, block, direction, source_file, src_ip, dst_ip):
        """Parse a single session block"""
        lines = block.strip().split('\n')
        
        try:
            # Parse timestamp
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)', lines[0])
            if not timestamp_match:
                return None
            timestamp = timestamp_match.group(1)
            
            # Parse Session line
            session_line = next((line for line in lines if line.startswith('Session:')), None)
            if not session_line:
                return None
            
            session_match = re.search(
                r'Session: ([\d.]+) \([^)]+\) -> ([\d.]+) \([^)]+\) \(ID: (\d+), Seq: (\d+)\)',
                session_line
            )
            if not session_match:
                return None
            
            session_src_ip, session_dst_ip, session_id, seq = session_match.groups()
            
            # Parse SKB pointers
            skb_pointers = self.parse_skb_pointers(lines)
            
            # Detect packet loss
            drop, drop_reason, corrupted_stages = self.detect_packet_loss(skb_pointers)
            
            # Parse latencies
            path1_latencies = self.parse_path_latencies(lines, "Path 1 Latencies")
            path2_latencies = self.parse_path_latencies(lines, "Path 2 Latencies")
            
            # Parse total RTT
            total_rtt = self.parse_total_rtt(lines)
            
            # Calculate max latency stage (excluding corrupted stages and total RTT)
            max_stage, max_latency = self.find_max_latency_excluding_corrupted(
                path1_latencies, path2_latencies, corrupted_stages
            )
            
            return {
                'timestamp': timestamp,
                'direction': direction,
                'source_file': source_file,
                'src_ip': src_ip,
                'dst_ip': dst_ip,
                'session_id': int(session_id),
                'seq': int(seq),
                'drop': drop,
                'drop_reason': drop_reason,
                'corrupted_stages': corrupted_stages,
                'skb_pointers': skb_pointers,
                'total_rtt': total_rtt,
                'max_stage': max_stage,
                'max_latency': max_latency,
                'path1_latencies': path1_latencies,
                'path2_latencies': path2_latencies,
                'session_line_src': session_src_ip,
                'session_line_dst': session_dst_ip
            }
            
        except Exception as e:
            print(f"Error parsing session: {e}")
            return None
    
    def parse_skb_pointers(self, lines):
        """Parse SKB pointers"""
        pointers = {}
        in_section = False
        
        for line in lines:
            if 'SKB Pointers' in line:
                in_section = True
                continue
            elif line.startswith('Path') and 'Latencies' in line:
                break
            elif in_section and line.strip():
                # Use more flexible matching
                match = re.search(r'Stage\s+(\d+)\s+.*?:\s+(0x[a-fA-F0-9]+)', line)
                if match:
                    stage_id, pointer = match.groups()
                    pointers[int(stage_id)] = pointer
                else:
                    # Manual split as fallback
                    parts = line.split(':')
                    if len(parts) >= 2 and 'Stage' in parts[0] and '0x' in parts[1]:
                        stage_match = re.search(r'Stage\s+(\d+)', parts[0])
                        hex_match = re.search(r'(0x[a-fA-F0-9]+)', parts[1])
                        if stage_match and hex_match:
                            stage_id = stage_match.group(1)
                            pointer = hex_match.group(1)
                            pointers[int(stage_id)] = pointer
        
        return pointers
    
    def detect_packet_loss(self, skb_pointers):
        """Detect packet loss - ensure correct detection of Stage 0==1 but Stage 1≠2 cases"""
        if 0 in skb_pointers and 1 in skb_pointers and 2 in skb_pointers:
            stage_0_ptr = skb_pointers[0]
            stage_1_ptr = skb_pointers[1]
            stage_2_ptr = skb_pointers[2]
            
            # Key detection: if stage 0 and 1 are same, but stage 1 and 2 are different -> packet loss
            if stage_0_ptr == stage_1_ptr and stage_1_ptr != stage_2_ptr:
                return True, "Stage_1_to_2_SKB_Mismatch", ["1->2"]
            
            # If stage 0 and 1 are already different -> also abnormal
            elif stage_0_ptr != stage_1_ptr:
                return True, "Stage_0_to_1_SKB_Mismatch", ["0->1"]
        
        return False, None, []
    
    def parse_path_latencies(self, lines, section_name):
        """Parse path latencies"""
        latencies = {}
        in_section = False
        
        for line in lines:
            if line.strip().startswith(section_name):
                in_section = True
                continue
            elif (line.strip().startswith('Path') or line.strip().startswith('Total')) and in_section:
                break
            elif in_section and line.strip():
                match = re.search(r'\[\s*(\d+)->(\d+)\s*\].*?:\s*([\d.]+|N/A)\s*us', line)
                if match:
                    start, end, latency_str = match.groups()
                    stage_key = f"{start}->{end}"
                    if latency_str != "N/A":
                        latencies[stage_key] = float(latency_str)
        
        return latencies
    
    def parse_total_rtt(self, lines):
        """Parse total RTT"""
        for line in lines:
            if 'Total RTT' in line and ':' in line:
                match = re.search(r'([\d.]+)\s*us', line)
                if match:
                    return float(match.group(1))
        return None
    
    def find_max_latency_excluding_corrupted(self, path1_latencies, path2_latencies, corrupted_stages):
        """Find max latency stage, excluding corrupted stages, not including total RTT"""
        max_latency = 0
        max_stage = None
        
        # Check Path1 stages (excluding corrupted stages)
        for stage_pair, latency in path1_latencies.items():
            if latency and stage_pair not in corrupted_stages:
                if latency > max_latency:
                    max_latency = latency
                    max_stage = f"Path1_{stage_pair}"
        
        # Check Path2 stages
        for stage_pair, latency in path2_latencies.items():
            if latency and latency > max_latency:
                max_latency = latency
                max_stage = f"Path2_{stage_pair}"
        
        return max_stage, max_latency
    
    def parse_log_file(self, file_path, direction, source_file, src_ip, dst_ip):
        """Parse a single log file"""
        sessions = []
        
        if not os.path.exists(file_path):
            print(f"Warning: File does not exist {file_path}")
            return sessions
            
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Split by ICMP RTT Trace, each section represents a session
        session_blocks = re.split(r'=== ICMP RTT Trace:', content)
        
        for i, block in enumerate(session_blocks[1:], 1):  # Skip first empty block
            session = self.parse_session_block(block, direction, source_file, src_ip, dst_ip)
            if session:
                sessions.append(session)
            
        return sessions
    
    def load_and_parse_data(self):
        """Load and parse data for all node pairs"""
        print("Starting to load network latency data...")
        self.sessions = []
        
        for pair in self.node_pairs:
            print(f"\nProcessing node pair: {pair['pair_name']}")
            pair_sessions = []
            
            # Parse outgoing file
            if pair['outgoing_file']:
                sessions = self.parse_log_file(
                    pair['outgoing_file'], 'OUTGOING', 
                    os.path.basename(pair['outgoing_file']),
                    pair['src_ip'], pair['dst_ip']
                )
                pair_sessions.extend(sessions)
                print(f"  Outgoing ({os.path.basename(pair['outgoing_file'])}): {len(sessions)} sessions")
            
            # Parse incoming file
            if pair['incoming_file']:
                sessions = self.parse_log_file(
                    pair['incoming_file'], 'INCOMING',
                    os.path.basename(pair['incoming_file']),
                    pair['src_ip'], pair['dst_ip']
                )
                pair_sessions.extend(sessions)
                print(f"  Incoming ({os.path.basename(pair['incoming_file'])}): {len(sessions)} sessions")
            
            # Add pair identifier
            for session in pair_sessions:
                session['pair_name'] = pair['pair_name']
            
            self.sessions.extend(pair_sessions)
        
        print(f"\nTotal loaded {len(self.sessions)} sessions from {len(self.node_pairs)} node pairs")
        return self.sessions
    
    def match_session_pairs_for_all_nodes(self):
        """Match session pairs for all node pairs"""
        print("\nStarting to match session pairs for all node pairs...")
        
        all_matched_pairs = []
        all_outgoing_only = []
        all_incoming_only = []
        
        # Group by pair_name
        sessions_by_pair = defaultdict(list)
        for session in self.sessions:
            sessions_by_pair[session['pair_name']].append(session)
        
        for pair_name, pair_sessions in sessions_by_pair.items():
            print(f"\nMatching {pair_name}:")
            
            # Group by direction
            outgoing_sessions = [s for s in pair_sessions if s['direction'] == 'OUTGOING']
            incoming_sessions = [s for s in pair_sessions if s['direction'] == 'INCOMING']
            
            print(f"  OUTGOING sessions: {len(outgoing_sessions)}")
            print(f"  INCOMING sessions: {len(incoming_sessions)}")
            
            # Build incoming session lookup dictionary
            incoming_lookup = {}
            for session in incoming_sessions:
                key = (session['session_id'], session['seq'])
                incoming_lookup[key] = session
            
            # Match session pairs
            matched_pairs = []
            outgoing_only = []
            
            for outgoing in outgoing_sessions:
                key = (outgoing['session_id'], outgoing['seq'])
                if key in incoming_lookup:
                    incoming = incoming_lookup[key]
                    matched_pairs.append((outgoing, incoming))
                else:
                    outgoing_only.append(outgoing)
            
            # Find incoming-only sessions
            matched_keys = set((out['session_id'], out['seq']) for out, _ in matched_pairs)
            incoming_only = [
                inc for inc in incoming_sessions
                if (inc['session_id'], inc['seq']) not in matched_keys
            ]
            
            print(f"  Successfully matched: {len(matched_pairs)} pairs")
            print(f"  Outgoing only: {len(outgoing_only)}")
            print(f"  Incoming only: {len(incoming_only)}")
            
            all_matched_pairs.extend(matched_pairs)
            all_outgoing_only.extend(outgoing_only)
            all_incoming_only.extend(incoming_only)
        
        return all_matched_pairs, all_outgoing_only, all_incoming_only
    
    def analyze_single_session_pair(self, outgoing_session, incoming_session, session_key):
        """Analyze a single session pair"""
        
        # Combined session analysis
        combined_analysis = {
            'session_key': session_key,
            'pair_name': outgoing_session['pair_name'],
            'session_type': 'bidirectional',
            'outgoing': outgoing_session,
            'incoming': incoming_session,
            'direction': f"{outgoing_session['src_ip']}->{outgoing_session['dst_ip']}",
            'session_id': outgoing_session['session_id'],
            'seq': outgoing_session['seq'],
            
            # Packet loss analysis - consider overall loss if either direction has loss
            'drop': outgoing_session['drop'] or incoming_session['drop'],
            'drop_details': [],
            
            # Record max latency stage for both directions separately
            'outgoing_max_stage': outgoing_session['max_stage'],
            'outgoing_max_latency': outgoing_session['max_latency'],
            'incoming_max_stage': incoming_session['max_stage'],
            'incoming_max_latency': incoming_session['max_latency'],
            
            # Overall max latency (larger of the two directions)
            'max_stage': None,
            'max_latency': 0,
            
            # Physical network delay and fping processing delay
            'physical_network_delay': None,
            'fping_processing_delay': None,
            
            # Complete latency data
            'outgoing_path1_latencies': outgoing_session['path1_latencies'],
            'outgoing_path2_latencies': outgoing_session['path2_latencies'],
            'incoming_path1_latencies': incoming_session['path1_latencies'],
            'incoming_path2_latencies': incoming_session['path2_latencies'],
            'outgoing_total_rtt': outgoing_session['total_rtt'],
            'incoming_total_rtt': incoming_session['total_rtt'],
            
            # Mark this as bidirectional data
            'is_bidirectional': True,
            'available_directions': ['OUTGOING', 'INCOMING']
        }
        
        # Record packet loss details
        if outgoing_session['drop']:
            combined_analysis['drop_details'].append(f"OUTGOING_{outgoing_session['drop_reason']}")
        if incoming_session['drop']:
            combined_analysis['drop_details'].append(f"INCOMING_{incoming_session['drop_reason']}")
        
        # Determine overall max latency stage
        if outgoing_session['max_latency'] >= incoming_session['max_latency']:
            combined_analysis['max_stage'] = f"OUTGOING_{outgoing_session['max_stage']}"
            combined_analysis['max_latency'] = outgoing_session['max_latency']
        else:
            combined_analysis['max_stage'] = f"INCOMING_{incoming_session['max_stage']}"
            combined_analysis['max_latency'] = incoming_session['max_latency']
        
        # Calculate physical network delay (outgoing path1 end to incoming path1 start)
        if outgoing_session['total_rtt'] and incoming_session['total_rtt']:
            combined_analysis['physical_network_delay'] = abs(
                outgoing_session['total_rtt'] - incoming_session['total_rtt']
            ) / 2
        
        # fping processing delay (simplified calculation)
        combined_analysis['fping_processing_delay'] = 50.0  # Assume fixed 50us
        
        return combined_analysis
    
    def generate_analysis_report(self):
        """Generate complete analysis report"""
        matched_pairs, outgoing_only, incoming_only = self.match_session_pairs_for_all_nodes()
        
        # Analysis results
        valid_sessions = []
        dropped_sessions = []
        
        print(f"\nStarting session analysis...")
        print(f"  Matched pairs: {len(matched_pairs)}")
        print(f"  Unidirectional outgoing: {len(outgoing_only)}")  
        print(f"  Unidirectional incoming: {len(incoming_only)}")
        
        # 1. Analyze matched session pairs
        print(f"\nAnalyzing {len(matched_pairs)} matched session pairs...")
        for i, (outgoing, incoming) in enumerate(matched_pairs):
            session_key = f"{outgoing['pair_name']}_{outgoing['session_id']}_{outgoing['seq']}"
            analysis = self.analyze_single_session_pair(outgoing, incoming, session_key)
            
            if analysis['drop']:
                dropped_sessions.append(analysis)
            else:
                valid_sessions.append(analysis)
        
        # 2. Analyze unidirectional outgoing sessions
        print(f"\nAnalyzing {len(outgoing_only)} unidirectional outgoing sessions...")
        for session in outgoing_only:
            session_key = f"{session['pair_name']}_OUTGOING_{session['session_id']}_{session['seq']}"
            analysis = self.analyze_single_unidirectional_session(session, session_key, 'OUTGOING')
            
            if analysis['drop']:
                dropped_sessions.append(analysis)
            else:
                valid_sessions.append(analysis)
        
        # 3. Analyze unidirectional incoming sessions  
        print(f"\nAnalyzing {len(incoming_only)} unidirectional incoming sessions...")
        for session in incoming_only:
            session_key = f"{session['pair_name']}_INCOMING_{session['session_id']}_{session['seq']}"
            analysis = self.analyze_single_unidirectional_session(session, session_key, 'INCOMING')
            
            if analysis['drop']:
                dropped_sessions.append(analysis)
            else:
                valid_sessions.append(analysis)
        
        # Generate statistics report
        total_sessions = len(matched_pairs) + len(outgoing_only) + len(incoming_only)
        
        print(f"\nAnalysis completed:")
        print(f"  Total sessions: {total_sessions}")
        print(f"  Matched pairs: {len(matched_pairs)}")
        print(f"  Unidirectional sessions: {len(outgoing_only) + len(incoming_only)}")
        print(f"  Valid sessions: {len(valid_sessions)}")
        print(f"  Dropped sessions: {len(dropped_sessions)}")
        
        # Prepare analysis results
        analysis_result = {
            'analysis': {
                'node_pairs': [
                    {
                        'pair_name': pair['pair_name'],
                        'src_ip': pair['src_ip'],
                        'dst_ip': pair['dst_ip'],
                        'direction': f"{pair['src_ip']}->{pair['dst_ip']}"
                    } for pair in self.node_pairs
                ],
                'timestamp': datetime.now().isoformat(),
                'total_sessions': total_sessions,
                'matched_sessions': len(matched_pairs),
                'outgoing_only': len(outgoing_only),
                'incoming_only': len(incoming_only),
                'valid_sessions': valid_sessions,
                'dropped_sessions': dropped_sessions
            }
        }
        
        return analysis_result
    
    def analyze_single_unidirectional_session(self, session, session_key, session_type):
        """Analyze a single unidirectional session"""
        analysis = {
            'session_key': session_key,
            'pair_name': session['pair_name'],
            'session_type': 'unidirectional',
            'direction_type': session_type,  # 'OUTGOING' or 'INCOMING'
            'direction': f"{session['src_ip']}->{session['dst_ip']}",
            'session_id': session['session_id'],
            'seq': session['seq'],
            'timestamp': session['timestamp'],
            
            # Packet loss analysis
            'drop': session['drop'],
            'drop_details': [f"{session_type}_{session['drop_reason']}"] if session['drop'] else [],
            
            # Latency analysis
            'max_stage': session['max_stage'],
            'max_latency': session['max_latency'],
            'total_rtt': session['total_rtt'],
            
            # Complete latency data
            'path1_latencies': session['path1_latencies'],
            'path2_latencies': session['path2_latencies'],
            
            # Mark this as unidirectional data
            'is_bidirectional': False,
            'available_direction': session_type
        }
        
        return analysis
    
    def save_analysis_report(self, report, output_file):
        """Save analysis report"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n📁 Analysis report saved: {output_file}")

def load_config_file(config_file):
    """Load configuration file"""
    with open(config_file, 'r', encoding='utf-8') as f:
        if config_file.endswith('.yaml') or config_file.endswith('.yml'):
            try:
                import yaml
                config = yaml.safe_load(f)
            except ImportError:
                print("Error: PyYAML is required to support YAML configuration files")
                print("Run: pip install pyyaml")
                return None
        else:
            config = json.load(f)
    return config

def main():
    parser = argparse.ArgumentParser(description='General Network Latency Analyzer')
    parser.add_argument('--config', '-c', help='Configuration file path (JSON or YAML format)')
    parser.add_argument('--src-ip', help='Source IP address')
    parser.add_argument('--dst-ip', help='Destination IP address') 
    parser.add_argument('--outgoing', help='Outgoing log file path')
    parser.add_argument('--incoming', help='Incoming log file path')
    parser.add_argument('--output-dir', '-o', default='.', help='Output directory (default: current directory)')
    parser.add_argument('--name', help='Analysis name (used for output file naming)')
    
    args = parser.parse_args()
    
    # Create analyzer
    analyzer = GeneralLatencyAnalyzer()
    
    if args.config:
        # Load from configuration file
        print(f"Loading from configuration file: {args.config}")
        config = load_config_file(args.config)
        if not config:
            return 1
        
        # Parse configuration
        node_pairs = config.get('node_pairs', [])
        for pair in node_pairs:
            analyzer.add_node_pair(
                src_ip=pair['src_ip'],
                dst_ip=pair['dst_ip'],
                outgoing_file=pair.get('outgoing_file'),
                incoming_file=pair.get('incoming_file'),
                pair_name=pair.get('name')
            )
        
        analysis_name = config.get('name', 'general_analysis')
        output_dir = config.get('output_dir', args.output_dir)
        
    else:
        # Load from command line arguments
        if not all([args.src_ip, args.dst_ip]):
            print("Error: Need to specify --src-ip and --dst-ip, or use --config to specify configuration file")
            return 1
        
        analyzer.add_node_pair(
            src_ip=args.src_ip,
            dst_ip=args.dst_ip,
            outgoing_file=args.outgoing,
            incoming_file=args.incoming,
            pair_name=args.name
        )
        
        analysis_name = args.name or f"{args.src_ip}-{args.dst_ip}"
        output_dir = args.output_dir
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Load and parse data
    analyzer.load_and_parse_data()
    
    # Generate analysis report
    analysis_report = analyzer.generate_analysis_report()
    
    # Save analysis.json
    analysis_file = os.path.join(output_dir, f"{analysis_name}_analysis.json")
    analyzer.save_analysis_report(analysis_report, analysis_file)
    
    # Generate summary report
    from general_summary_generator import GeneralSummaryGenerator
    summary_generator = GeneralSummaryGenerator(analysis_file)
    summary = summary_generator.generate_summary()
    
    # Save summary.json
    summary_file = os.path.join(output_dir, f"{analysis_name}_latency_summary.json")
    summary_generator.save_summary(summary, summary_file)
    
    # Print summary
    summary_generator.print_summary(summary)
    
    return 0

if __name__ == "__main__":
    exit(main()) 