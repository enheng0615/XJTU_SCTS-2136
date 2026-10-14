---
name: cluster-slurm
description: 在配置的 CPU 集群通过 SSH/Slurm 查询实时资源、规划并提交计算任务。用户要求在集群运行、调试、批量提交或查询作业时使用；不要在登录/管理节点直接运行计算程序。
---

# CPU 集群作业

首次使用先运行 `python3 <本技能目录>/scripts/cluster.py configure --host HOST --ssh-user USER --login-hostname NAME`，将集群地址或 SSH 别名、个人账号及登录节点 hostname 保存到本机 `~/.config/cluster-slurm/config.json`；这些信息不随技能发布。配置后运行 `inspect` 验证连接与节点身份。服务器手册中的节点数量、分区和模块版本可能过时，必须查询实时配置。登录节点只用于编辑、传输、轻量编译、查询和提交；不要在这里运行 Python 计算、训练、仿真、数据处理或后台进程。

## 每次提交

1. 先运行 `python3 <本技能目录>/scripts/cluster.py inspect`。向用户展示当前 CPU 节点数量、总核数、Slurm 空闲核数、可用内存、实际负载异常节点和可用 QoS；不要把 `sinfo` 中重复出现的分区节点相加。库存是瞬时快照。
2. 确认任务类型（串行、线程、MPI、混合、独立数组）、总进程数、每进程线程数、节点数、**每节点**峰值内存、最长时间、远端脚本和工作目录。缺失峰值内存、时间或并行模型时向用户提问，不猜测。若程序已提供日志/历史结果，可先据此估算并明确说明估算依据。独立任务用数组并询问并发上限；用户关联多个 Slurm account 时询问计费账号，传入 `--account`。
3. `python3 <本技能目录>/scripts/cluster.py plan --kind ... --tasks ... --cpus-per-task ... --nodes ... --mem-gb ... --time DD-HH:MM:SS`。脚本按**实时** QoS 上限选择最小能容纳任务的 CPU 分区，并检查节点当前 CPU、内存和实际负载。`plan` 只做只读查询。
4. 在远端工作目录准备作业脚本。脚本以 `#!/bin/bash` 开头，只包含运行命令、必要的 `module load`/环境激活及显式输出路径；资源参数统一由 `cluster.py` 提交，脚本里不要写 `#SBATCH`。不要在登录节点直接试跑计算命令；需要调试时申请小型 Slurm 交互任务。大任务先以真实输入的小样本做独立 Slurm 作业。
5. 紧接提交前重新运行 `submit`；它重新检查资源，并用命令行参数覆盖脚本中的资源指令，同时把作业限制在检查过的安全节点。仅当 `plan` 显示可立即容纳、远端脚本和工作目录存在时提交。默认不在资源不足时排队；用户明确接受排队可加 `--allow-queue`，但任务必须满足总容量与 QoS 限制。提交后报告 job ID、作业名、分区、QoS、资源、节点、工作目录、日志路径及本机监控状态文件。`submit` 成功后自动启动独立的本机监控进程，默认每 3 分钟查询 Slurm；用户可用 `--monitor-interval 秒数` 调整。监控记录排队、运行和终态，在检测到任务失败、取消、超时、OOM、异常队列状态或查询失败时立即发本机系统通知，并把告警写入状态文件。用 `monitor.py show --job-id ID` 读取记录，并用 `cluster.py status --job-id ID` 直接核对 Slurm。若监控启动失败，作业仍可能已提交，必须报告 job ID 和 `monitor_error`，可用 `monitor.py start --job-id ID` 补启。若 `sbatch` 响应超时，**不要直接重试**，先用 `cluster.py list` 按唯一作业名检查是否已提交，避免重复作业。

示例（数值仅作格式示范，实际资源需由用户需求确定）：

```bash
python3 <本技能目录>/scripts/cluster.py inspect
python3 <本技能目录>/scripts/cluster.py plan --kind threaded --tasks 1 --cpus-per-task 8 --nodes 1 --mem-gb 32 --time 02:00:00
python3 <本技能目录>/scripts/cluster.py submit --kind threaded --tasks 1 --cpus-per-task 8 --nodes 1 --mem-gb 32 --time 02:00:00 --script /home/USER/work/job.sh --workdir /home/USER/work
```

`--kind array` 还需 `--array-count N --max-parallel M`，资源参数按**单个数组元素**填写。不得用 `nohup`、`screen`、`tmux`、`ssh LOGIN_NODE 'python ...'` 等方式绕过调度器。Hook 会拦截常见直接 SSH 执行，但无法替代服务器端权限控制。

监控进程只在提交者的本机运行，不占用登录节点。状态保存在 `~/.local/state/cluster-slurm/<主机>/<job-id>.json`（或 `XDG_STATE_HOME` 下），含最近查询时间、状态变化、失败原因、告警投递结果和数组完成情况。`monitor.py stop --job-id ID` 仅停止本机监控，**不会取消 Slurm 作业**。本机关机、睡眠或网络中断时无法持续监控；恢复后可用 `monitor.py start --job-id ID` 重新附着，并以 Slurm 状态为准。系统通知依赖本机通知服务；跨 Codex、Claude Code、Trae 的后台进程不能保证向已结束的 AI 会话发消息。

若 Agent 会话仍在等待作业结果，定期用 `monitor.py show --job-id ID` 检查状态并在发现异常时立即在会话内报告；长时作业在会话结束后由本机系统通知提醒用户。告警检测延迟最长约为配置的轮询间隔，SSH 查询失败时会退避，不能保证故障发生的同一瞬间送达。

若脚本报告节点负载与 Slurm 分配明显不符、内存探测失败、作业无内存请求或配置不明，不要把该节点视为安全空闲；给出证据并请用户/管理员确认。
