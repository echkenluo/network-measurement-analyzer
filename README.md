# 网络测量分析器

集群网络性能测量与分析工具集，提供网络延迟、丢包、CPU性能等多维度分析。

## 项目结构

```
network-measurement-analyzer/
├── network-monitor-analyzer/    # 网络监控分析
├── latency-analyzer/           # 网络延迟分析
├── cpu_monitor/               # CPU性能监控
├── drop-analyzer/             # 丢包分析
└── data/                      # 数据存储目录
```

## 模块说明

### 1. 网络监控分析 (network-monitor-analyzer)

分析集群网络监控日志，统计丢包率和高延迟情况。

```bash
cd network-monitor-analyzer
python3 network_monitor_log_summary.py network_config.json
```

**输入**: 网络日志文件 + 节点配置文件  
**输出**: 网络质量分析报告

### 2. 延迟分析 (latency-analyzer)

分析ICMP网络延迟数据，支持多节点对延迟测量。

```bash
cd latency-analyzer/system-network/icmp
python3 general_latency_analyzer.py --config config.json
```

**输入**: ICMP延迟日志 + 节点配置  
**输出**: 延迟分析报告和汇总数据

### 3. CPU监控 (cpu_monitor)

监控和分析CPU性能指标。

```bash
cd cpu_monitor
./cpu_monitor.sh
```

**输入**: 系统CPU数据  
**输出**: CPU性能分析报告

### 4. 丢包分析 (drop-analyzer)

分析网络丢包情况和PPS性能。

```bash
cd drop-analyzer/vnet
python3 alert_pps_analysis.py
```

**输入**: 网络丢包数据  
**输出**: 丢包分析结果

## 快速开始

1. 选择需要的分析模块
2. 准备相应的配置文件和数据文件
3. 运行对应的分析脚本
4. 查看生成的分析报告

## 配置文件

各模块的配置文件位于对应的 `cluster_config/` 或 `config/` 目录下，包含节点IP、文件路径等配置信息。 