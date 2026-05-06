#!/usr/bin/env bash
# =============================================================================
# Hermes WebUI — 部署脚本（本地开发验证 / 阿里云生产部署）
#
# 用法:
#   ./scripts/deploy.sh                    # 交互模式
#   ./scripts/deploy.sh --check            # 只做检查，不部署
#   ./scripts/deploy.sh --server IP --key  # 非交互模式
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="hermes-webui"
IMAGE_TAG="latest"
REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_KEY="${REMOTE_KEY:-}"
REGISTRY="${REGISTRY:-}"
DEPLOY_MODE="${DEPLOY_MODE:-docker-compose}"  # docker-compose | docker-run

# ── Color output ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()  { echo -e "${BLUE}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERR]${RESET}  $*" >&2; }
step()  { echo -e "${CYAN}[STEP]${RESET} ${BOLD}$*${RESET}"; }

# ── Help ─────────────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
${BOLD}Hermes WebUI 部署脚本${RESET}

${BOLD}用法:${RESET}
  $0 [选项]

${BOLD}选项:${RESET}
  --check              只做检查，不构建也不部署
  --server HOST        远程主机 IP/域名（必填，非交互模式）
  --key FILE           SSH 私钥路径（默认: ~/.ssh/id_ed25519）
  --port NUM           SSH 端口（默认: 22）
  --user USER          远程用户（默认: root）
  --registry URL       Docker registry URL（可选）
  --mode MODE          部署模式: docker-compose（默认）| docker-run
  --skip-tests         跳过测试
  --skip-build         跳过 Docker 构建（使用已有镜像）
  -h, --help           显示本帮助

${BOLD}示例:${RESET}
  $0 --check
  $0 --server 47.239.65.9 --key ~/.ssh/hermes.pem
  $0 --server my-server.com --registry registry.example.com --mode docker-run
EOF
    exit 0
}

# ── Parse args ───────────────────────────────────────────────────────────────
CHECK_ONLY=false; SKIP_TESTS=false; SKIP_BUILD=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)         CHECK_ONLY=true; shift ;;
        --server)        REMOTE_HOST="$2"; shift 2 ;;
        --key)           REMOTE_KEY="$2"; shift 2 ;;
        --port)          REMOTE_PORT="$2"; shift 2 ;;
        --user)          REMOTE_USER="$2"; shift 2 ;;
        --registry)      REGISTRY="$2"; shift 2 ;;
        --mode)          DEPLOY_MODE="$2"; shift 2 ;;
        --skip-tests)    SKIP_TESTS=true; shift ;;
        --skip-build)    SKIP_BUILD=true; shift ;;
        -h|--help)       usage ;;
        *) error "未知参数: $1"; usage ;;
    esac
done

[[ -z "$REMOTE_KEY" ]] && REMOTE_KEY="$HOME/.ssh/id_ed25519"

# ── Pre-flight checks ────────────────────────────────────────────────────────
step "Pre-flight checks"

check_command() {
    if ! command -v "$1" &>/dev/null; then
        error "命令未找到: $1"
        MISSING_DEPS=true
    fi
}

MISSING_DEPS=false
check_command docker
check_command git
[[ -d "$PROJECT_ROOT/.git" ]] && check_command gh

if [[ "$MISSING_DEPS" == true ]]; then
    error "缺少依赖命令，请先安装"
    exit 1
fi

if [[ ! -f "$PROJECT_ROOT/Dockerfile" ]]; then
    error "Dockerfile 不存在: $PROJECT_ROOT/Dockerfile"
    exit 1
fi

ok "依赖检查通过"

# ── Local tests ──────────────────────────────────────────────────────────────
if [[ "$SKIP_TESTS" != true ]]; then
    step "运行单元测试"
    if [[ -f "$PROJECT_ROOT/bootstrap.py" ]]; then
        if python "$PROJECT_ROOT/bootstrap.py" 2>/dev/null; then
            ok "bootstrap.py 通过"
        else
            warn "bootstrap.py 失败，继续部署（可加 --skip-tests 跳过）"
        fi
    fi

    if [[ -d "$PROJECT_ROOT/tests" ]]; then
        info "运行 pytest（可加 --skip-tests 跳过）..."
        if command -v pytest &>/dev/null; then
            # Run in background to keep output flowing; check exit code
            if pytest "$PROJECT_ROOT/tests" -q --tb=line 2>&1 | tail -3; then
                ok "测试全部通过"
            else
                warn "测试有失败，继续部署"
            fi
        fi
    fi
else
    info "跳过测试（--skip-tests）"
fi

# ── Build Docker image ───────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" != true ]]; then
    step "构建 Docker 镜像"
    DOCKER_BUILD_ARGS=(--tag "${IMAGE_NAME}:${IMAGE_TAG}")
    [[ -n "$REGISTRY" ]] && DOCKER_BUILD_ARGS+=(--tag "${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}")

    DOCKER_BUILDKIT=1 docker build "${DOCKER_BUILD_ARGS[@]}" "$PROJECT_ROOT"
    ok "镜像构建完成: ${IMAGE_NAME}:${IMAGE_TAG}"
else
    info "跳过构建（--skip-build）"
fi

if [[ "$CHECK_ONLY" == true ]]; then
    ok "检查模式完成，未实际部署"
    exit 0
fi

# ── Deploy to remote ────────────────────────────────────────────────────────
if [[ -z "$REMOTE_HOST" ]]; then
    if [[ -t 0 ]]; then
        echo -n "请输入远程主机 IP/域名（留空则在本地部署）: "
        read -r REMOTE_HOST
    fi
    [[ -z "$REMOTE_HOST" ]] && REMOTE_HOST="localhost"
fi

if [[ "$REMOTE_HOST" == "localhost" ]]; then
    step "本地部署（Docker Compose）"
    cd "$PROJECT_ROOT"
    if [[ -f docker-compose.yml ]]; then
        docker compose down 2>/dev/null || true
        docker compose up -d --build
        ok "本地部署完成: http://localhost:8787"
    else
        error "本地需要 docker-compose.yml"
        exit 1
    fi
    exit 0
fi

# ── Remote deployment ───────────────────────────────────────────────────────
step "部署到远程: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"

SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10
         -p "$REMOTE_PORT")
[[ -f "$REMOTE_KEY" ]] && SSH_CMD+=(-i "$REMOTE_KEY")
SSH_CMD+=("${REMOTE_USER}@${REMOTE_HOST}")

# Verify connectivity
info "测试 SSH 连接..."
if ! "${SSH_CMD[@]}" "echo ok" &>/dev/null; then
    error "SSH 连接失败，请检查 host/key/port"
    exit 1
fi
ok "SSH 连接成功"

# Transfer image as tarball if no registry
if [[ -z "$REGISTRY" ]]; then
    info "导出镜像为 tarball（无 registry，推送改为 tarball 传输）..."
    IMAGE_TAR="/tmp/${IMAGE_NAME}.${IMAGE_TAG}.tar.gz"
    docker save "${IMAGE_NAME}:${IMAGE_TAG}" | gzip -c > "$IMAGE_TAR"
    ok "镜像导出完成: $(du -sh "$IMAGE_TAR" | cut -f1)"

    info "传输镜像到远程主机..."
    scp -o StrictHostKeyChecking=accept-new -i "$REMOTE_KEY" \
        -P "$REMOTE_PORT" "$IMAGE_TAR" \
        "${REMOTE_USER}@${REMOTE_HOST}:/tmp/${IMAGE_NAME}.${IMAGE_TAG}.tar.gz"

    info "在远程主机加载镜像..."
    "${SSH_CMD[@]}" "docker load -i /tmp/${IMAGE_NAME}.${IMAGE_TAG}.tar.gz && rm /tmp/${IMAGE_NAME}.${IMAGE_TAG}.tar.gz"
    ok "镜像加载完成"
    rm -f "$IMAGE_TAR"
fi

# Deploy
info "执行远程部署..."
if [[ "$DEPLOY_MODE" == "docker-compose" ]]; then
    "${SSH_CMD[@]}" bash -s <<'REMOTE_SCRIPT'
set -e
IMAGE_NAME="hermes-webui"; IMAGE_TAG="latest"
cd /opt/hermes-webui 2>/dev/null || cd ~/hermes-webui 2>/dev/null || { mkdir -p /opt/hermes-webui && cd /opt/hermes-webui; }
echo "[INFO] Working dir: $(pwd)"
# Copy project files if docker-compose.yml exists locally
if [[ -f /tmp/docker-compose.yml ]] 2>/dev/null; then
    cp /tmp/docker-compose.yml .
fi
docker compose down 2>/dev/null || true
docker compose up -d --build
echo "[ OK ] Deployed. Check: docker compose ps"
REMOTE_SCRIPT
elif [[ "$DEPLOY_MODE" == "docker-run" ]]; then
    "${SSH_CMD[@]}" "docker run -d --name hermes-webui \
        --restart unless-stopped \
        -p 8787:8787 \
        -v ~/.hermes:/home/hermes/.hermes:ro \
        ${IMAGE_NAME}:${IMAGE_TAG}"
fi

ok "部署完成！"
info "访问地址: http://${REMOTE_HOST}:8787"
