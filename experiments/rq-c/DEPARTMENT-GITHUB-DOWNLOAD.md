# P2-R GitHub download for the department computer

P2-R uses a dedicated, clean Git checkout of [korose523/AIJADE](https://github.com/korose523/AIJADE). Use the full commit SHA from the AIJADE delivery record for offline preparation. The formal approval must identify the exact source commit used later. The Chapter 7 Mac qualification and its build are separate from this department workflow.

## Download the exact source

In a POSIX shell, set `AIJADE_WORKSPACE_ROOT` to your dedicated, existing AIJADE workspace and `AIJADE_DOWNLOAD_COMMIT` to the full 40-character commit SHA. The workspace will contain the checkout and a separate directory for private records. On the Mac use `/Volumes/Untitled/AIJADE/`. Allow room for the checkout and its retained inputs.

```sh
set -eu
: "${AIJADE_WORKSPACE_ROOT:?Set the existing workspace path}"
: "${AIJADE_DOWNLOAD_COMMIT:?Set the full delivery commit SHA}"
test "${#AIJADE_DOWNLOAD_COMMIT}" -eq 40
case "$AIJADE_DOWNLOAD_COMMIT" in *[!0-9a-f]*) exit 64 ;; esac

cd "$AIJADE_WORKSPACE_ROOT"
checkout="$PWD/department-source-$AIJADE_DOWNLOAD_COMMIT"
test ! -e "$checkout"
git init --quiet "$checkout"
git -C "$checkout" remote add origin https://github.com/korose523/AIJADE.git
git -C "$checkout" fetch --no-tags --depth=1 origin "$AIJADE_DOWNLOAD_COMMIT"
git -C "$checkout" checkout --detach FETCH_HEAD
test "$(git -C "$checkout" rev-parse HEAD)" = "$AIJADE_DOWNLOAD_COMMIT"
test -z "$(git -C "$checkout" status --porcelain=v1 --untracked-files=all --ignore-submodules=none)"
```

The launcher reads Git HEAD and checks the complete worktree against its approved receipt. GitHub's source ZIP and tarball lack the Git metadata the launcher requires. The full checkout also includes the nine archived input files consumed by the P2-R worklist.

## Check the downloaded inputs offline

From the same shell, with Python 3.12 available, generate the plan into a private directory outside the checkout.

```sh
private="$PWD/department-private-$AIJADE_DOWNLOAD_COMMIT"
mkdir -m 700 "$private"
cd "$checkout"
python3 -B experiments/rq-c/launch_department_regeneration.py plan > "$private/offline-plan.json"
```

The plan checks those nine pinned files and three complete archived populations of 7,200 rows. Its status is `OFFLINE_COMMAND_PLAN`. Retain the checkout SHA, the reported `worklistSha256` and the generated JSON. The command reads local files and leaves qualification and regeneration at `NOT_RUN`.

## Prepare the assigned host

After the supervisor's reply and host allocation, use the [launch and evidence guide](DEPARTMENT-REGENERATION-LAUNCH.md) to pin the exact Linux .NET SDK and runner build from the approved checkout. The runner projects are `tools/Aijade.Rqc/Aijade.Rqc.csproj` and `tools/Aijade.Substrate/Aijade.Substrate.csproj`. Record their full dependency directories and keep the approval receipt, logs and model material private.

For a Linux NVIDIA host, review the [journal collector guide](DEPARTMENT-JOURNAL-COLLECTOR.md) and run its offline configuration check before the host evidence checks. Verify the actual service, NVIDIA device identity, log visibility and retention window under the assigned account. Use the documented qualification and regeneration entries only with the reviewed plan and their required evidence.
