# 网络监控分析器

网络监控日志分析工具，用于分析集群网络质量，包括丢包率、高延迟统计等。

## 基本用法

### 1. 网络日志分析

```bash
python3 network_monitor_log_summary.py network_config.json [--source highlatency|network-monitor]
```

### 2. 生成汇总报告

```bash
python3 generate_summary.py network_analysis_report.txt
```

## 输入文件

### 配置文件 (network_config.json)
```json
{
  "nodes": {
    "/path/to/node1/logs": {
      "storage_ip": "192.168.254.31",
      "management_ip": "10.216.19.31"
    }
  }
}
```

### 日志文件
- **highlatency模式**: `network-high-latencies.log`
- **network-monitor模式**: `network-monitor.log*`

## 输出文件

- `network_analysis_report.txt` - 详细分析报告
- `network_summary_report.md` - 汇总报告（Markdown格式）

## 数据源选项

- `--source highlatency` (默认): 分析高延迟日志
- `--source network-monitor`: 分析网络监控日志（自动过滤包含lost_num的数据）

## 配置示例

参考 `cluster_config/` 目录下的配置文件：
- `network_config_example.json` - 基本配置示例
- `network_config.json` - 实际配置文件 