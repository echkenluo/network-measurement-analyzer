# Network Configuration Batch Tool

批量配置多台服务器网络参数的工具。

## 使用方法

```bash
# 基本用法
./batch_network_config.sh config.txt

# 干运行模式（仅验证）
./batch_network_config.sh config.txt --dry-run

# 命令行覆盖参数
./batch_network_config.sh config.txt --set net.core.busy_read=50
```

## 配置文件格式

```
# network_configs
net.core.busy_read=0
net.core.busy_poll=0
net.core.netdev_max_backlog=1000

# nodes
192.168.1.100,root,password123
192.168.1.101,root,password456
```

- `# network_configs` 后跟网络参数设置
- `# nodes` 后跟服务器信息（IP,用户名,密码）

vm_config.txt 为修改其中两个 vm  net.core.busy_read=0 的示例配置。

## 输出结果

生成报告文件：`network_config_report_YYYYMMDD_HHMMSS.txt`

包含每个节点的配置状态、验证结果和错误信息。