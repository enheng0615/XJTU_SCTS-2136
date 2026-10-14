---
name: cluster-slurm
description: 在已配置的 CPU Slurm 集群查询资源、规划、提交和监控计算作业。用户要在服务器集群跑程序、提交 sbatch 或数组作业、查看队列与剩余资源、排查作业失败时使用。
---

# XJTU_SCTS- 2136 CPU 集群作业

登录节点只用于编辑、传输、轻量编译、查询和提交。不得在这里运行 Python 计算、训练、仿真、数据处理或后台计算进程；不得用 `nohup`、`screen`、`tmux` 或直接 SSH 绕过 Slurm。Hook 只能拦截部分直接 SSH 命令，不能替代服务器端权限控制。

首次使用先在用户本机运行 `python3 <本技能目录>/scripts/cluster.py configure --host HOST --ssh-user USER --login-hostname NAME`，再运行 `inspect` 验证连接与登录节点身份。`NAME` 是远端 `hostname` 的输出。认证由用户本机 SSH 提供；不要在技能、聊天或仓库中保存密码和私钥。

## 按请求选择流程

- **查剩余资源或能否运行：**运行 `cluster.py inspect`，说明总核数、Slurm 空闲核数、安全可用内存、异常节点和可用 QoS。实时快照不是资源预留；不要把不同分区里重复出现的节点相加。只查询时不要求提交参数。
- **规划或提交新作业：**阅读 [references/submission.md](references/submission.md)。先查资源，确认并行模型、每节点峰值内存和最长时间，运行 `plan`；只有用户要求运行且条件满足时才运行 `submit`。缺关键参数时提问，不猜测。不能在登录节点试跑计算程序。
- **查询或监控已有作业：**用 `cluster.py status --job-id ID` 核对 Slurm；用 `monitor.py show --job-id ID` 查看本机记录。用户要求改变已有作业的查询频率时，用 `monitor.py interval --job-id ID --interval 秒数`。持续显示多个作业、控制页面开关、重启监控或处理告警时阅读 [references/monitoring.md](references/monitoring.md)。用户不希望弹出页面时用 `dashboard.py disable`；关闭页面不会停止独立监控和异常提醒。查询状态不进入提交流程，也不自动重提失败作业。

脚本路径相对于本技能目录。服务器手册中的节点数量、分区及模块版本可能过时，资源与 QoS 均以实时查询为准。若节点负载与 Slurm 分配明显不符、内存探测失败或配置不明，停止将该节点视为安全空闲，并向用户报告证据。
