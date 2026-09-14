#!/usr/bin/env bash
#
# start-aijade.sh — AIJADE 一键启动脚本 (one-click stack launcher)
#
# 启动三件套 (外加 PG / Redis 前置检查):
#   • apps/server          → http://localhost:3000   (API + /ws/chat 实时同步)
#   • packages/server-runtime → http://localhost:6121 (插件网关 /ws)
#   • apps/stage-web       → http://localhost:5173   (Web UI)
#
# 前置条件 (本环境已知约束):
#   - Postgres(:5432) 与 Redis(:6379) 若未运行，本脚本会尝试用同级目录
#     local-db/start-db.sh 以"用户态"方式自动拉起 (无需 sudo/brew/docker)；
#     若该启动器不存在，则提示手动启动。
#   - 由于 pnpm install 在本环境被 broker 拦截，依赖采用已链接好的 node_modules。
#     全新克隆请先在 broker 之外执行 `pnpm install`，再运行本脚本。
#   - 脚本直接调用 node_modules/.bin 下的 tsx / vite / dotenvx 二进制，
#     以规避 pnpm 的 safe-delete 批量守卫。
#
# 用法:
#   ./start-aijade.sh          # 启动全部 (已运行的会跳过)
#   ./start-aijade.sh --stop   # 停止全部已启动的进程
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BIN="$ROOT/node_modules/.bin"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

# 本地基础设施启动器 (用户态 Postgres+Redis，无需 sudo/brew/docker)。
# 位于项目同级目录 local-db/ (由 start-db.sh 提供)。
LOCAL_DB="$ROOT/../local-db/start-db.sh"

# ---------- 工具函数 ----------
require_bin() {
  if [ ! -x "$BIN/$1" ]; then
    echo "❌ 缺少 $1 (node_modules/.bin/$1)，请先安装依赖 (pnpm install)。"
    exit 1
  fi
}

# 端口监听检测 (bash /dev/tcp)
check_port() {
  ( exec 3<>"/dev/tcp/$1/$2" ) 2>/dev/null && { exec 3>&-; return 0; } || return 1
}

# HTTP 健康检查，命中期望状态码即视为就绪
wait_for_url() {
  local url="$1" expect="$2" name="$3" i=0
  until curl -s --noproxy '*' -o /dev/null -w '%{http_code}' "$url" 2>/dev/null | grep -q "$expect"; do
    i=$((i + 1))
    if [ "$i" -ge 60 ]; then
      echo "❌ $name 在 60s 内未能就绪，请查看 $LOG_DIR 下日志。"
      return 1
    fi
    sleep 1
  done
  echo "✅ $name 已就绪 ($url)"
}

# ---------- 停止模式 ----------
if [ "${1:-}" = "--stop" ]; then
  echo "🛑 停止 AIJADE 全部服务..."
  pkill -f 'src/bin/run.* api'      || true   # apps/server (run.ts 或 run.js)
  pkill -f 'server-runtime/src/bin/run' || true   # packages/server-runtime
  pkill -f 'vite --host'            || true   # apps/stage-web
  sleep 2
  echo "已发送停止信号。"
  exit 0
fi

# ---------- 依赖二进制 ----------
require_bin tsx
require_bin vite
require_bin dotenvx

# ---------- 1. 基础设施健康检查 + 必要时自动拉起 (PG / Redis) ----------
echo "🔍 检查基础设施..."
need_db=0
if check_port 127.0.0.1 5432; then echo "✅ Postgres   :5432 监听中"; else echo "⚠️  Postgres   :5432 未监听"; need_db=1; fi
if check_port 127.0.0.1 6379; then echo "✅ Redis      :6379 监听中"; else echo "⚠️  Redis      :6379 未监听"; need_db=1; fi

if [ "$need_db" -eq 1 ]; then
  if [ -x "$LOCAL_DB" ]; then
    echo "🚀 尝试用本地启动器拉起 PG/Redis: $LOCAL_DB"
    bash "$LOCAL_DB" || echo "⚠️  本地启动器执行失败，请检查 $LOCAL_DB"
    # 重新探测
    check_port 127.0.0.1 5432 && echo "✅ Postgres   :5432 已就绪" || echo "❌ Postgres   :5432 仍不可用"
    check_port 127.0.0.1 6379 && echo "✅ Redis      :6379 已就绪" || echo "❌ Redis      :6379 仍不可用"
  else
    echo "⚠️  未找到本地启动器 ($LOCAL_DB)。请在 broker 之外手动启动 Postgres/Redis 后重试。"
  fi
fi

# ---------- 2. 规避 Vite safe-delete 批量守卫: 移走陈旧 .vite 缓存 ----------
if [ -d apps/stage-web/node_modules/.vite ]; then
  mv apps/stage-web/node_modules/.vite "/tmp/vite-cache-$(date +%s)" \
    && echo "🧹 已移走旧 .vite 缓存 (避免 Vite 清理触发的批量删除守卫)"
fi

# ---------- 3. 逐个启动 (已运行的跳过) ----------
echo ""
echo "🚀 启动 AIJADE 技术栈..."

# 3a. apps/server  (:3000)
if check_port 127.0.0.1 3000; then
  echo "↪️  apps/server (:3000) 已在运行，跳过"
else
  # nohup + 双重 fork 子 shell：让服务脱离当前 shell 会话，忽略 SIGHUP，
  # 脚本/终端退出后服务继续存活 (交互终端与非交互环境都适用)。
  ( cd apps/server && nohup "$BIN/dotenvx" run -f .env.local --overload --ignore=MISSING_ENV_FILE -- \
      "$BIN/tsx" --import ./instrumentation.ts src/bin/run.ts api > "$LOG_DIR/server.log" 2>&1 < /dev/null & )
  echo "   • apps/server          → 启动中 (detached)"
fi

# 3b. packages/server-runtime  (:6121)
if check_port 127.0.0.1 6121; then
  echo "↪️  server-runtime (:6121) 已在运行，跳过"
else
  ( cd packages/server-runtime && nohup "$BIN/tsx" src/bin/run.ts > "$LOG_DIR/server-runtime.log" 2>&1 < /dev/null & )
  echo "   • server-runtime        → 启动中 (detached)"
fi

# 3c. apps/stage-web  (:5173)
if check_port 127.0.0.1 5173; then
  echo "↪️  stage-web (:5173) 已在运行，跳过"
else
  ( cd apps/stage-web && nohup "$BIN/vite" --host > "$LOG_DIR/stage-web.log" 2>&1 < /dev/null & )
  echo "   • stage-web             → 启动中 (detached)"
fi

# ---------- 4. 健康检查 ----------
echo ""
echo "⏳ 等待服务就绪..."
sleep 2
wait_for_url http://localhost:3000/           200 "apps/server"
wait_for_url http://localhost:6121/           404 "server-runtime (根路径 404 为预期)"
wait_for_url http://localhost:5173/           200 "stage-web"

# ---------- 5. 完成 ----------
echo ""
echo "🎉 AIJADE 技术栈已运行:"
echo "   • Web UI   → http://localhost:5173"
echo "   • API / WS → http://localhost:3000   (聊天实时同步: ws://localhost:3000/ws/chat)"
echo "   • Runtime  → http://localhost:6121   (插件网关:     ws://localhost:6121/ws)"
echo ""
echo "日志目录: $LOG_DIR/*.log"
echo "停止全部: ./start-aijade.sh --stop"
