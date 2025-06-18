# 延迟分析器

ICMP网络延迟数据分析工具，支持多节点对的延迟测量分析，提供详细的延迟分布和阶段统计。

## 基本用法

### 1. 延迟数据分析

```bash
cd system-network/icmp
python3 general_latency_analyzer.py --config cluster_config/config.json
```

### 2. 命令行模式

```bash
python3 general_latency_analyzer.py --src-ip 192.168.254.32 --dst-ip 192.168.254.42 \
    --outgoing tx.log --incoming rx.log --name analysis_name
```

### 3. 生成汇总报告

```bash
python3 general_summary_generator.py results/analysis_name_analysis.json
```

## 输入文件

### 配置文件格式 (JSON)
```json
{
  "name": "analysis_name",
  "description": "Network latency analysis",
  "output_dir": "results",
  "node_pairs": [
    {
      "name": "Node1->Node2",
      "src_ip": "192.168.254.31",
      "dst_ip": "192.168.254.32",
      "outgoing_file": "/path/to/outgoing.log",
      "incoming_file": "/path/to/incoming.log"
    }
  ]
}
```

### 日志文件
- **outgoing日志**: 发送方向的ICMP延迟跟踪数据
- **incoming日志**: 接收方向的ICMP延迟跟踪数据

## 输出文件

- `{name}_analysis.json` - 详细的session分析数据
- `{name}_latency_summary.json` - 延迟分布统计汇总
- 控制台输出延迟分布报告

## 分析功能

- **延迟分布分析**: 0-10ms、10-100ms、100-500ms等区间统计
- **阶段分析**: 各个网络处理阶段的延迟分布
- **丢包检测**: SKB指针不匹配检测
- **双向匹配**: 自动匹配outgoing和incoming会话
- **多节点支持**: 支持批量分析多个节点对

## 配置示例

参考 `cluster_config/` 目录下的配置文件：
- `intel-*.json` - Intel平台配置
- `amd-*.json` - AMD平台配置

## 分析结果

Results目录包含各种集群的分析结果，文件命名格式：
- `{cluster}_analysis.json` - 原始分析数据
- `{cluster}_latency_summary.json` - 汇总统计
- `延迟数据汇总表.md` - Markdown格式汇总表
- `网络延迟分析报告.md` - 详细分析报告 