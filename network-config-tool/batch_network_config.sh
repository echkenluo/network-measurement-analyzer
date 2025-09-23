#!/bin/bash

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_debug() { echo -e "${PURPLE}[DEBUG]${NC} $1"; }

# 全局变量
CONFIG_FILE=""
DRY_RUN=false
REPORT_FILE=""
TOTAL_NODES=0
SUCCESS_COUNT=0
FAIL_COUNT=0

# 网络配置变量 - 从配置文件中读取
NETWORK_CONFIG_LIST=""

# 节点数组
declare -a NODES_DATA=()

# 获取配置值
get_config_value() {
    local key="$1"
    echo "$NETWORK_CONFIG_LIST" | grep "^$key=" | cut -d'=' -f2-
}

# 设置配置值
set_config_value() {
    local key="$1"
    local value="$2"

    # 如果配置已存在，替换它
    if [ -n "$NETWORK_CONFIG_LIST" ] && echo "$NETWORK_CONFIG_LIST" | grep -q "^$key="; then
        NETWORK_CONFIG_LIST=$(echo "$NETWORK_CONFIG_LIST" | sed "s/^$key=.*/$key=$value/")
    else
        # 否则添加新配置
        if [ -z "$NETWORK_CONFIG_LIST" ]; then
            NETWORK_CONFIG_LIST="$key=$value"
        else
            NETWORK_CONFIG_LIST="$NETWORK_CONFIG_LIST
$key=$value"
        fi
    fi
}

# 获取所有配置键
get_all_config_keys() {
    echo "$NETWORK_CONFIG_LIST" | grep "=" | cut -d'=' -f1
}

# 检查依赖
check_dependencies() {
    log_info "Checking dependencies..."

    # 检查ssh和scp
    if ! command -v ssh >/dev/null 2>&1; then
        log_error "ssh is required but not installed"
        exit 1
    fi

    if ! command -v scp >/dev/null 2>&1; then
        log_error "scp is required but not installed"
        exit 1
    fi

    # 检查sshpass（用于密码认证）
    if ! command -v sshpass >/dev/null 2>&1; then
        log_warning "sshpass not found. Password authentication may not work."
        log_warning "Install with: sudo apt-get install sshpass"
    fi

    log_success "Dependencies check passed"
}

# 解析配置文件
parse_config() {
    log_info "Parsing configuration file: $CONFIG_FILE"

    if [ ! -f "$CONFIG_FILE" ]; then
        log_error "Configuration file not found: $CONFIG_FILE"
        exit 1
    fi

    local stage=""
    local config_count=0
    local node_count=0

    while IFS= read -r line; do
        # 去除前后空格
        line=$(echo "$line" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')

        # 跳过空行
        if [ -z "$line" ]; then
            continue
        fi

        # 检查stage标记
        if [ "$line" = "# network_configs" ]; then
            stage="configs"
            continue
        elif [ "$line" = "# nodes" ]; then
            stage="nodes"
            continue
        fi

        # 跳过其他注释行
        if echo "$line" | grep -q "^#"; then
            continue
        fi

        # 解析网络配置（network_configs后的配置行）
        if [ "$stage" = "configs" ]; then
            if echo "$line" | grep -q "="; then
                local key=$(echo "$line" | cut -d'=' -f1)
                local value=$(echo "$line" | cut -d'=' -f2- | sed 's/^"//;s/"$//')
                set_config_value "$key" "$value"
                config_count=$((config_count + 1))
                log_debug "Network config: $key=$value"
            fi
        fi

        # 解析VM配置（nodes后的所有行）
        if [ "$stage" = "nodes" ]; then
            if echo "$line" | grep -q ","; then
                NODES_DATA+=("$line")
                node_count=$((node_count + 1))
            fi
        fi
    done < "$CONFIG_FILE"

    TOTAL_NODES=$node_count

    if [ "$TOTAL_NODES" -eq 0 ]; then
        log_error "No nodes found in configuration file"
        exit 1
    fi

    log_success "Configuration parsing completed"
    log_info "Found $TOTAL_NODES nodes to configure"
    log_info "Found $config_count network configurations"

    # 显示将要应用的配置
    log_info "Network configurations to apply:"
    for key in $(get_all_config_keys); do
        local value=$(get_config_value "$key")
        log_info "  $key = $value"
    done
}

# SSH连接函数
ssh_connect() {
    local host="$1"
    local port="$2"
    local username="$3"
    local password="$4"
    local command="$5"

    if command -v sshpass >/dev/null 2>&1; then
        sshpass -p "$password" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -p "$port" "$username@$host" "$command"
    else
        # 使用expect来处理密码输入
        expect << EOF
spawn ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -p $port $username@$host "$command"
expect {
    "password:" { send "$password\r"; exp_continue }
    "Password:" { send "$password\r"; exp_continue }
    eof
}
EOF
    fi
}

# 检查节点连接
check_node_connection() {
    local host="$1"
    local port="$2"
    local username="$3"
    local password="$4"

    log_debug "Testing connection to $host" >&2

    if ssh_connect "$host" "$port" "$username" "$password" "echo 'connection test'" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# 备份当前sysctl配置
backup_sysctl_config() {
    local host="$1"
    local port="$2"
    local username="$3"
    local password="$4"

    log_debug "Backing up sysctl configuration on $host" >&2

    local backup_file="/etc/sysctl.conf.backup.$(date +%Y%m%d_%H%M%S)"

    if ssh_connect "$host" "$port" "$username" "$password" "sudo cp /etc/sysctl.conf $backup_file" >/dev/null 2>&1; then
        echo "$backup_file"
        return 0
    else
        return 1
    fi
}

# 应用网络配置
apply_network_configs() {
    local host="$1"
    local port="$2"
    local username="$3"
    local password="$4"

    log_debug "Applying network configurations on $host" >&2

    # 构建配置命令
    local config_commands=""
    for key in $(get_all_config_keys); do
        local value=$(get_config_value "$key")
        # 首先检查配置是否已存在，如果存在则更新，否则添加
        config_commands="$config_commands
# 处理配置: $key
if grep -q '^$key=' /etc/sysctl.conf; then
    sudo sed -i 's/^$key=.*/$key=$value/' /etc/sysctl.conf
else
    echo '$key=$value' | sudo tee -a /etc/sysctl.conf
fi"
    done

    # 添加应用配置的命令
    config_commands="$config_commands
# 应用配置
sudo sysctl -p"

    if ssh_connect "$host" "$port" "$username" "$password" "$config_commands" 2>&1; then
        return 0
    else
        return 1
    fi
}

# 验证配置是否生效
verify_configs() {
    local host="$1"
    local port="$2"
    local username="$3"
    local password="$4"

    log_debug "Verifying configurations on $host" >&2

    local all_verified=true
    local verify_results=""

    for key in $(get_all_config_keys); do
        local expected_value=$(get_config_value "$key")

        # 简化验证 - 直接检查sysctl输出中是否包含期望的键值对
        local verification_result=$(ssh_connect "$host" "$port" "$username" "$password" "sysctl $key 2>/dev/null | grep -q '$key = $expected_value' && echo 'OK' || echo 'FAIL'" 2>/dev/null | tail -1 | tr -d '\r\n' | tr -d ' ')

        if [ "$verification_result" = "OK" ]; then
            verify_results="$verify_results$key: OK (value=$expected_value)\n"
        else
            # 获取实际值用于报告
            local actual_value=$(ssh_connect "$host" "$port" "$username" "$password" "sysctl -n $key 2>/dev/null" 2>/dev/null | tail -1 | tr -d '\r\n' | tr -d ' ')
            verify_results="$verify_results$key: FAILED (expected: $expected_value, actual: $actual_value)\n"
            all_verified=false
        fi
    done

    echo -e "$verify_results"

    if [ "$all_verified" = true ]; then
        return 0
    else
        return 1
    fi
}

# 配置单个节点
configure_node() {
    local node_index="$1"
    local node_data="$2"

    # 解析节点数据 (格式: ip,username,password)
    local host=$(echo "$node_data" | cut -d',' -f1)
    local username=$(echo "$node_data" | cut -d',' -f2)
    local password=$(echo "$node_data" | cut -d',' -f3)
    local port=22  # 默认端口
    local node_name="$host"  # 使用IP作为节点名

    local start_time=$(date +%s)
    local steps_completed=""
    local backup_file=""
    local verification_result=""
    local error_message=""
    local success=false

    log_info "Starting network configuration for $node_name ($host)"

    # 1. 检查连接
    if check_node_connection "$host" "$port" "$username" "$password"; then
        steps_completed="$steps_completed,connection_verified"
        log_debug "Connection verified"
    else
        error_message="Connection failed"
        write_node_result "$node_index" "$node_name" "$host" "$success" "$error_message" "$steps_completed" "$backup_file" "$verification_result" "$start_time"
        return 1
    fi

    # 2. 备份当前配置
    if backup_file=$(backup_sysctl_config "$host" "$port" "$username" "$password"); then
        steps_completed="$steps_completed,config_backed_up"
        log_debug "Configuration backed up to $backup_file"
    else
        error_message="Configuration backup failed"
        write_node_result "$node_index" "$node_name" "$host" "$success" "$error_message" "$steps_completed" "$backup_file" "$verification_result" "$start_time"
        return 1
    fi

    # 3. 应用配置（如果不是dry-run模式）
    if [ "$DRY_RUN" = true ]; then
        steps_completed="$steps_completed,dry_run_completed"
        verification_result="dry-run mode - configurations not applied"
        success=true
        log_success "Dry-run completed for $node_name"
    else
        if apply_network_configs "$host" "$port" "$username" "$password"; then
            steps_completed="$steps_completed,configs_applied"
            log_debug "Network configurations applied"

            # 4. 验证配置
            if verification_result=$(verify_configs "$host" "$port" "$username" "$password"); then
                steps_completed="$steps_completed,configs_verified"
                success=true
                log_success "Network configuration for $node_name completed successfully"
            else
                error_message="Configuration verification failed"
                log_error "Verification failed for $node_name"
            fi
        else
            error_message="Configuration application failed"
        fi
    fi

    write_node_result "$node_index" "$node_name" "$host" "$success" "$error_message" "$steps_completed" "$backup_file" "$verification_result" "$start_time"

    if [ "$success" = true ]; then
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        return 0
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        return 1
    fi
}

# 写入节点结果到报告文件
write_node_result() {
    local node_index="$1"
    local node_name="$2"
    local host="$3"
    local success="$4"
    local error_message="$5"
    local steps_completed="$6"
    local backup_file="$7"
    local verification_result="$8"
    local start_time="$9"

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # 清理steps_completed（移除前导逗号）
    steps_completed="${steps_completed#,}"

    # 写入结果到临时文件（文本格式）
    cat >> "$REPORT_FILE.tmp" << EOF
Node: $node_name ($host)
Status: $([ "$success" = "true" ] && echo "SUCCESS" || echo "FAILED")
Duration: ${duration}s
Steps Completed: $steps_completed
Backup File: $backup_file
$([ -n "$error_message" ] && echo "Error: $error_message")
Verification Results:
$verification_result
Start Time: $(date -d @$start_time --iso-8601=seconds 2>/dev/null || date -r $start_time)
End Time: $(date -d @$end_time --iso-8601=seconds 2>/dev/null || date -r $end_time)
----------------------------------------
EOF
}

# 配置所有节点
configure_all() {
    log_info "Starting batch network configuration..."
    echo "============================================================"

    # 初始化报告文件
    REPORT_FILE="network_config_report_$(date +'%Y%m%d_%H%M%S')"
    > "$REPORT_FILE.tmp"

    SUCCESS_COUNT=0
    FAIL_COUNT=0

    # 遍历所有节点
    for i in "${!NODES_DATA[@]}"; do
        local node_data="${NODES_DATA[$i]}"
        local host=$(echo "$node_data" | cut -d',' -f1)

        log_info "Processing node $((i+1))/$TOTAL_NODES: $host"

        configure_node "$i" "$node_data" || true

        echo "----------------------------------------"
        sleep 1  # 短暂延迟避免过快连接
    done

    generate_final_report
    print_summary
}

# 生成最终报告
generate_final_report() {
    local configuration_time=$(date --iso-8601=seconds 2>/dev/null || date)

    # 创建文本格式的配置报告
    cat > "$REPORT_FILE.txt" << EOF
========================================
Network Configuration Report
========================================
Configuration Time: $configuration_time
Total Nodes: $TOTAL_NODES
Successful: $SUCCESS_COUNT
Failed: $FAIL_COUNT

Applied Configurations:
EOF

    # 添加配置信息
    for key in $(get_all_config_keys); do
        local value=$(get_config_value "$key")
        echo "  $key = $value" >> "$REPORT_FILE.txt"
    done

    cat >> "$REPORT_FILE.txt" << EOF

========================================
Configuration Details
========================================
EOF

    # 添加所有节点结果
    cat "$REPORT_FILE.tmp" >> "$REPORT_FILE.txt"

    # 添加摘要
    cat >> "$REPORT_FILE.txt" << EOF

========================================
Summary
========================================
EOF

    if [ $SUCCESS_COUNT -gt 0 ]; then
        echo "✓ SUCCESSFUL CONFIGURATIONS: $SUCCESS_COUNT" >> "$REPORT_FILE.txt"
        grep -A 15 "Status: SUCCESS" "$REPORT_FILE.tmp" | grep "Node:" | sed 's/Node: /  • /' >> "$REPORT_FILE.txt"
    fi

    if [ $FAIL_COUNT -gt 0 ]; then
        echo "" >> "$REPORT_FILE.txt"
        echo "✗ FAILED CONFIGURATIONS: $FAIL_COUNT" >> "$REPORT_FILE.txt"
        grep -A 15 "Status: FAILED" "$REPORT_FILE.tmp" | grep "Node:" | sed 's/Node: /  • /' >> "$REPORT_FILE.txt"
    fi

    cat >> "$REPORT_FILE.txt" << EOF

========================================
Useful Commands
========================================
View current sysctl settings:
  sysctl -a | grep net.core

Verify specific setting:
  sysctl net.core.busy_read

Reload sysctl configurations:
  sysctl -p

Restore from backup (if needed):
  sudo cp /etc/sysctl.conf.backup.YYYYMMDD_HHMMSS /etc/sysctl.conf
  sudo sysctl -p
EOF

    # 清理临时文件
    rm -f "$REPORT_FILE.tmp"

    log_success "Detailed report saved to $REPORT_FILE.txt"
}

# 打印摘要
print_summary() {
    echo
    echo "============================================================"
    echo "NETWORK CONFIGURATION SUMMARY"
    echo "============================================================"

    log_info "Total nodes: $TOTAL_NODES"
    log_success "Successful: $SUCCESS_COUNT"
    log_error "Failed: $FAIL_COUNT"

    # 显示应用的配置
    echo
    echo -e "${CYAN}Applied Network Configurations:${NC}"
    for key in $(get_all_config_keys); do
        local value=$(get_config_value "$key")
        echo "  $key = $value"
    done

    if [ $SUCCESS_COUNT -gt 0 ]; then
        echo
        echo -e "${GREEN}✓ SUCCESSFUL CONFIGURATIONS:${NC}"
        echo "  All $SUCCESS_COUNT nodes configured successfully"
        echo "  Network settings have been applied and are persistent"
    fi

    if [ $FAIL_COUNT -gt 0 ]; then
        echo
        echo -e "${RED}✗ FAILED CONFIGURATIONS:${NC}"
        echo "  $FAIL_COUNT node(s) failed to configure"
        echo "  Check the detailed report for error information"
    fi

    echo
    echo "Detailed report: $REPORT_FILE.txt"
}

# 显示帮助信息
show_help() {
    cat << EOF
Network Configuration Batch Tool

Usage: $0 <config_file> [options]

Arguments:
  config_file    配置文件路径

Options:
  --set KEY=VALUE          设置单个网络配置参数
  --dry-run               仅验证配置，不执行配置
  -h, --help              显示帮助信息

配置文件格式:
  # network_configs
  net.core.busy_read=0
  net.core.busy_poll=0
  net.core.netdev_max_backlog=1000

  # nodes
  192.168.79.23,root,password123
  192.168.72.171,root,password456

Examples:
  $0 network_config.txt
  $0 network_config.txt --dry-run
  $0 network_config.txt --set net.core.busy_read=50
  $0 network_config.txt --set net.core.busy_read=0 --set net.core.busy_poll=100

Dependencies:
  - ssh, scp (SSH tools)
  - sshpass (for password authentication, optional)

Install dependencies:
  Ubuntu/Debian: sudo apt-get install sshpass
  CentOS/RHEL:   sudo yum install sshpass

EOF
}

# 主函数
main() {
    # 先保存原始参数用于后续处理
    local original_args=("$@")

    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --set)
                # 暂时跳过，稍后处理
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                if [ -z "$CONFIG_FILE" ]; then
                    CONFIG_FILE="$1"
                else
                    log_error "Too many arguments"
                    show_help
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # 检查必需参数
    if [ -z "$CONFIG_FILE" ]; then
        log_error "Missing required argument: config_file"
        show_help
        exit 1
    fi

    echo "========================================"
    echo "Network Configuration Batch Tool"
    echo "========================================"
    echo

    if [ "$DRY_RUN" = true ]; then
        log_info "Running in dry-run mode - validating configuration only"
    fi

    # 执行配置流程
    check_dependencies
    parse_config

    # 现在处理命令行覆盖
    set -- "${original_args[@]}"
    while [[ $# -gt 0 ]]; do
        case $1 in
            --set)
                if echo "$2" | grep -q "="; then
                    local key=$(echo "$2" | cut -d'=' -f1)
                    local value=$(echo "$2" | cut -d'=' -f2-)
                    set_config_value "$key" "$value"
                    log_info "Override config: $key=$value"
                    shift 2
                else
                    log_error "Invalid format for --set. Use: --set KEY=VALUE"
                    exit 1
                fi
                ;;
            *)
                shift
                ;;
        esac
    done

    if [ "$DRY_RUN" = true ]; then
        log_success "Configuration validation passed"
        log_info "Would apply the following configurations:"
        for key in $(get_all_config_keys); do
            local value=$(get_config_value "$key")
            log_info "  $key = $value"
        done
        exit 0
    fi

    configure_all
}

# 执行主函数
main "$@"