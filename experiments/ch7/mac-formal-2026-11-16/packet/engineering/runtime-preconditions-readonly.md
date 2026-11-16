# Mac 正式后端准备：当前只读清点

当前快照见 `runtime-preconditions-readonly.json`，观察时间为 2026-11-16 08:34 UTC。没有进行模型推理、renderer 启动、压力测试或 admission，没有停止/重启服务，也没有输出环境变量或凭据。本记录属于准备检查，不是正式后端资格或新科学测量。

## 当前可复用状态

| 项目 | 当前证据及路径 |
| --- | --- |
| POSIX runtime | `/Volumes/Untitled/AIJADE/.runtime/posix` 是已挂载、可写 APFS，快照空闲 14,005,014,528 字节，约 13.04 GiB。没有在该处做新的写入/Unix socket 探针。 |
| 源码与新证据 | `/Volumes/Untitled/AIJADE/AIJADE-next` 与本次 `.research/runs/ch7-mac-formal-20261116` 在 macFUSE 文件系统，和 runtime 的 device 不同；不能把源码目录称为 APFS。 |
| Colima | 状态命令成功；项目状态根为 `.runtime/posix/colima`，VM 为 x86_64、2 CPU、2 GiB 内存、8 GiB 磁盘。 |
| Docker socket | `.runtime/posix/colima/default/docker.sock` 存在；本次只读取该项目 socket 下的项目容器。 |
| PostgreSQL | `aijade-next-db` 运行，镜像 `ghcr.io/tensorchord/vchord-postgres:pg18-v1.0.0`，端口仅 `127.0.0.1:55432`；容器二进制报告 PostgreSQL 18.0，`pg_isready` 退出码 0。没有读取密码或测试 SQL 身份认证。 |
| Redis | `aijade-next-redis` 运行，仅 `127.0.0.1:56379`；PING=PONG，INFO 报告 7.4.12。 |
| .NET | 项目显式路径 `/Users/mac/.dotnet/dotnet` 存在，可枚举 8.0.425、10.0.401/402/403；当前项目 `global.json` 要求 10.0.403。PATH 默认指向另一个 `/usr/local/share/dotnet/dotnet`，后续应继续显式固定项目 SDK。 |
| Godot | `/Users/mac/.local/share/mosaic/godot-4.5.2/Godot_mono.app/Contents/MacOS/Godot` 存在且可执行；旧受限版本检查回执为 `4.5.2.stable.mono.official.6ce3de25a`。本次没有启动 Godot。 |
| Renderer 副本 | `/Volumes/Untitled/AIJADE/.research/runs/ch7-relocation-20261116/prepared-renderer` 及 `aijade-prepared-renderer.json` 存在；marker 列出的 112 个文件全部重算 SHA256 一致，没有缺失或变化。没有执行其 launcher。 |
| 私有 PMX | `/Volumes/Untitled/AIJADE/references/private-renderer-assets/m2/明音凛1.1.pmx` 存在，8,443,240 字节，SHA256 `0151ed94ef82d4d53684b614333ec46f20b59750db59b88db0819dbd74caab53`。 |
| 旧准备输入 | 当前 checkout 的 `experiments/ch7` 下 9 份历史 `prepared.json` 仍存在，逐项路径与 SHA256 在 JSON 清单；存在性不代表能跳过原输入、构建或资格核验。 |

主机观察为 x86_64，4 个物理 CPU 核、8 个逻辑 CPU、16 GiB RAM。本次未测 GPU 内存或设备可用性。最初 controller 日志的 `Apple_unified_CPU_GPU_memory` 标签未经核实，已在权威 JSON 与 collector 中纠正为内存/GPU 拓扑未表征；不要将该初始标签用于论文或资格结论。

## 当前准入阻断与服务归属

目前没有 dotnet 或 Godot 进程。Ollama 来自已存在的全局桌面 App：PID 669 的 `/Applications/Ollama.app/Contents/MacOS/Ollama`，子服务 PID 701。服务在 `127.0.0.1:11434`，`/api/version` 为 0.40.16；只读 `/api/ps` 返回空模型列表。没有找到将这两个全局进程登记为本轮项目自有、可随意终止的 ownership 回执，应按共享服务处理。此清点没有停止 App、服务或卸载模型。

冻结的 `experiments/ch7/admit_live_manifest_repeat.py:51` 按进程名采集所有 `dotnet`、`ollama` 和 Godot 进程，不根据 `/api/ps` 是否为空区分。现存共享 Ollama 因而仍会触发该前置条件；空模型列表不能替代准入要求，也不能为了得到通过结果临时改变采集规则。

旧 `.runtime/posix/runs/ch7-relocation-20261116/qualification-01/admission/receipt.json` 已记录：120 秒、60 个样本，最低可用内存 6,402,031,616 字节，swap-used 极差 0，但 `noResearchProcesses=false`，所以 `NOT_ADMITTED_NO_MEASUREMENT`。资格序列的已完成条件记录、块与模型请求均为 0，`formalHardwareQualification=false`。旧 launch 明确 `secondAdmissionAuthorized=false`，不能用它授权新的 admission；新的前瞻计划需单独明确边界并协调共享服务。

后续需要解决的不是缺少安装，而是共享 Ollama 的协调门槛、正式执行源码与二进制身份绑定，以及新计划规定的完整 settling/admission。上述工作均未在本轮只读清点中执行。
