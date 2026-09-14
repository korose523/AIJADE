# ---------------------------------------------------------------------------
# AIJADE · RQ-C 实验可复现环境
#
# 目的：让第三方一键重建环境并复现实验（ACM Artifact Functional 徽章要求）。
#   构建：docker build -t aijade-rqc:latest .
#   运行：docker run --rm -v "$(pwd)/docker-out:/out" aijade-rqc:latest
#   校验：连跑两次到不同目录，比对两次 summary.json 的 shasum，必须完全一致
#
# 运行时锁定（审查 §2.2）：
#   - Node 固定 22.12（与根 package.json 的 engines.node>=22.0.0 一致）
#   - pnpm 固定 10.33.0（与 packageManager 字段一致）
#   - 依赖由 --frozen-lockfile 锁定
#
# 注：不用 corepack —— node:22.12 内置 corepack 的信任密钥不含 pnpm 10.33.0 的
# 新签名密钥 id，会报 "Cannot find matching keyid" 而构建失败。改用 npm 直装，
# 版本号仍然硬锁定，不影响可复现性。
# ---------------------------------------------------------------------------
FROM node:22.12-bookworm-slim

ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:$PATH" \
    CI=true

RUN npm install -g pnpm@10.33.0 --no-fund --no-audit \
    && pnpm --version

WORKDIR /app

# ---- 1) 先只复制清单文件，最大化 layer cache ----
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml .npmrc ./
COPY patches/ ./patches/
COPY packages/research-harness/package.json packages/research-harness/
COPY packages/skill-forge-store/package.json packages/skill-forge-store/
COPY packages/skill-bench-env/package.json packages/skill-bench-env/

# 只装实验所需的 workspace 包及其依赖（全量 node_modules 约 5.5GB，不适合进镜像）
# --ignore-scripts：跳过 electron / sharp / onnxruntime 等根 devDependency 的二进制
# 下载（它们与实验无关，且在受限网络下会直接构建失败）。tsx 依赖的 esbuild 使用
# 平台可选依赖 @esbuild/linux-x64 提供二进制，不依赖 postinstall。
# --filter '!aijade' 排除根项目：根 package.json 的 devDependencies（electron /
# histoire / duckdb-wasm / mediapipe 等 2700+ 包）与实验无关，且会触发 pnpm 的
# 嵌套 node_modules 重命名错误。tsx 依赖的 esbuild 使用平台可选依赖
# @esbuild/linux-x64 提供二进制，不依赖 postinstall。
RUN pnpm install \
      --filter "@proj-aijade/research-harness..." \
      --filter '!aijade' \
      --frozen-lockfile \
      --ignore-scripts \
    && node_modules/.bin/tsx --version

# ---- 2) 再复制源码 ----
COPY packages/research-harness packages/research-harness
COPY packages/skill-forge-store packages/skill-forge-store
COPY packages/skill-bench-env packages/skill-bench-env

WORKDIR /app/packages/research-harness

# 默认跑 mock 后端：确定性、不依赖模型权重，同 seed 两次运行逐字节一致。
# 如需真实 LLM（宿主机 ollama）：
#   docker run --rm -v "$(pwd)/docker-out:/out" aijade-rqc:latest \
#     sh -c 'mkdir -p /out && ../../node_modules/.bin/tsx src/cli.ts \
#       --backend ollama --model qwen2.5-coder:7b-instruct \
#       --ollama-base-url http://host.docker.internal:11434 --out /out'
CMD ["sh", "-c", "mkdir -p /out && ../../node_modules/.bin/tsx src/cli.ts --backend mock --seed 42 --out /out"]
