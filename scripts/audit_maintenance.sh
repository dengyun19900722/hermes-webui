#!/usr/bin/env bash
# =============================================================================
# Hermes WebUI — 审计日志定时维护脚本
#
# 功能：
#   1. 压缩 audit-{date}.jsonl 老日志文件为 .jsonl.gz
#   2. 删除超过保留期的 .jsonl.gz 压缩文件
#
# 用法（直接运行）:
#   ./scripts/audit_maintenance.sh                        # 使用默认值
#   ./scripts/audit_maintenance.sh http://localhost:8787  # 指定实例
#
# 用法（cron 调度 — 每日凌晨 3 点执行）:
#   crontab -e
#   0 3 * * * /opt/hermes-webui/scripts/audit_maintenance.sh http://localhost:8787 >> /var/log/hermes-audit-maintenance.log 2>&1
#
# 参数（可选）:
#   $1  实例URL          （默认: http://localhost:8787）
#   $2  压缩阈值（天）   （默认: 7，7天以上压缩）
#   $3  清理阈值（天）   （默认: 90，90天以上的压缩包删除）
# =============================================================================

set -euo pipefail

URL="${1:-http://localhost:8787}"
ROTATE_DAYS="${2:-7}"
CLEANUP_DAYS="${3:-90}"

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

log()  { echo "$LOG_PREFIX [INFO]  $*"; }
logw() { echo "$LOG_PREFIX [WARN]  $*" >&2; }
loge() { echo "$LOG_PREFIX [ERROR] $*" >&2; }

# ── 健康检查 ────────────────────────────────────────────────────────────────
health_url="${URL}/api/health"
if ! curl -sf --max-time 5 "$health_url" >/dev/null 2>&1; then
    loge "实例不可达: $URL"
    loge "请确认 hermes-webui 已启动且端口可达"
    exit 1
fi

log "开始审计日志维护 — 实例: $URL"

# ── 1. 压缩老日志 ──────────────────────────────────────────────────────────
log "步骤 1/2: 压缩 ${ROTATE_DAYS} 天以上的 .jsonl 文件..."
rotate_url="${URL}/api/audit/rotate?days=${ROTATE_DAYS}"
rotate_resp=$(curl -sf --max-time 30 "$rotate_url" 2>&1) || {
    loge "压缩请求失败: $rotate_resp"
    exit 1
}

rotated=$(echo "$rotate_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rotated',0))" 2>/dev/null || echo "?")
skipped=$(echo "$rotate_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('skipped',0))" 2>/dev/null || echo "?")
errors=$(echo "$rotate_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('errors',0))" 2>/dev/null || echo "?")

if [ "$errors" -gt 0 ] 2>/dev/null; then
    logw "压缩完成: rotated=$rotated skipped=$skipped errors=$errors"
    logw "有压缩失败（见上方日志），可能文件正在被写入"
else
    log "压缩完成: rotated=$rotated skipped=$skipped"
fi

# ── 2. 清理超期压缩包 ──────────────────────────────────────────────────────
log "步骤 2/2: 删除超过 ${CLEANUP_DAYS} 天的压缩文件..."
cleanup_url="${URL}/api/audit/cleanup?days=${CLEANUP_DAYS}"
cleanup_resp=$(curl -sf --max-time 30 "$cleanup_url" 2>&1) || {
    loge "清理请求失败: $cleanup_resp"
    exit 1
}

deleted=$(echo "$cleanup_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('deleted',0))" 2>/dev/null || echo "?")
skipped_c=$(echo "$cleanup_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('skipped',0))" 2>/dev/null || echo "?")
detail=$(echo "$cleanup_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail',''))" 2>/dev/null || echo "")

if [ -n "$detail" ]; then
    log "清理结果: $detail"
else
    log "清理完成: deleted=$deleted skipped=$skipped_c"
fi

log "审计日志维护完成 — $(date '+%Y-%m-%d %H:%M:%S')"
