# RQ-C 实验容器化复现

本文件说明如何用一个干净的 Docker 容器重建 RQ-C 实验环境并复现结果。
目标：满足 ACM Artifact Evaluation 的 **Functional 徽章**（第三方可一键重建并复现）。

## 0. 前置：Docker 运行时

本机没有 Docker Desktop 与 root 权限，使用纯用户态的 colima：

```bash
export PATH="$HOME/.local/bin:$PATH"

colima status                       # 查看状态
colima start --cpu 4 --memory 8 --disk 40 --vm-type=vz --network-address=false
docker version                      # 应显示 Server 29.x（跑在 colima 的 Linux VM 内）
colima stop                         # 用完停掉
```

> colima 不随系统自启：**每次重启后需先 `colima start`** 再执行下面的构建/运行。

## 1. 构建

在仓库根目录执行（`.dockerignore` 已排除 `node_modules`、`experiments`、
`ollama-models`、`third_party`、`apps/**` 等无关内容）：

```bash
docker build -t aijade-rqc:latest .
```

运行时锁定（对应审查报告 §2.2「缺运行时锁定与环境封装」）：

| 项 | 锁定值 | 依据 |
|---|---|---|
| Node | `22.12`（`node:22.12-bookworm-slim`） | 根 `package.json` 的 `engines.node >= 22.0.0` |
| pnpm | `10.33.0`（npm 全局直装） | 根 `package.json` 的 `packageManager` |
| 依赖 | `--frozen-lockfile` | `pnpm-lock.yaml` |

> 为何不用 corepack：`node:22.12` 内置 corepack 的信任密钥不含 pnpm 10.33.0 的
> 新签名密钥 id，构建会报 `Cannot find matching keyid`。改用 `npm i -g pnpm@10.33.0`，
> 版本号仍然硬锁定，不影响可复现性。

依赖安装使用 `--filter "@proj-aijade/research-harness..."`（`...` 语法会连带安装其
workspace 依赖：`skill-forge-store`、`skill-bench-env`），避免把全仓 5.5 GB 的
`node_modules` 装进镜像。

## 2. 运行（默认 mock 后端 · 确定性）

`mock` 后端不依赖任何模型权重，同 seed 两次运行结果逐字节一致，是复现性验证的首选：

```bash
mkdir -p /tmp/rqc-out1 /tmp/rqc-out2

docker run --rm -v /tmp/rqc-out1:/out aijade-rqc:latest
docker run --rm -v /tmp/rqc-out2:/out aijade-rqc:latest
```

产物：`/out/rq-c-s42-mock-t30-r5/{trials.jsonl,summary.json}`。

### 确定性自证

```bash
shasum -a 256 /tmp/rqc-out1/rq-c-s42-mock-t30-r5/summary.json \
              /tmp/rqc-out2/rq-c-s42-mock-t30-r5/summary.json
```

两次 hash **必须完全一致**。

## 3. 运行（真实 LLM 后端 · 需宿主机 ollama）

容器内通过 `host.docker.internal` 访问宿主机的 ollama 服务：

```bash
# 宿主机先确认服务在跑
curl -s http://localhost:11434/api/version

mkdir -p /tmp/rqc-live
docker run --rm -v /tmp/rqc-live:/out aijade-rqc:latest \
  sh -c 'mkdir -p /out && ../../node_modules/.bin/tsx src/cli.ts \
    --backend ollama --model qwen2.5-coder:7b-instruct \
    --ollama-base-url http://host.docker.internal:11434 --out /out'
```

真实后端**不保证**逐字节可复现（取决于模型版本与解码），因此徽章验证以 mock 后端为准，
真实后端作为论文主结果（live 数据）单独报告，并在 `summary.json` 的 `sampling.mode`
字段中显式标注 `live` 与 `simulation`。

## 4. 校验基线

mock 运行的 `summary.json` 关键字段基线：

```
nSkills          = 2199
nExecutions      = 7200
precision (4 格) = 0.497 / 0.609 / 0.682 / 0.701
analysisUnit     = 'skill'
```

容器内跑出的数字应与宿主机一致；若不一致，属环境差异，需排查后如实报告。

## 5. 已知局限

- 镜像平台为 `linux/amd64`（本机构建于 Intel Mac）。在 Apple Silicon 上构建需加
  `--platform linux/amd64`，性能会受影响。
- 首次构建需要联网拉取基础镜像与 npm 依赖；构建完成后离线可重复运行（layer cache）。
- `experiments/` 目录被 `.dockerignore` 排除，宿主机实验产物不会进入镜像
  （可在容器内用 `ls /app/experiments` 验证为空）。
