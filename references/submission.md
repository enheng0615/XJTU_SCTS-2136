# 规划与提交

1. 运行 `python3 <本技能目录>/scripts/cluster.py inspect`，向用户展示当前 CPU 节点、可用核数、内存、异常节点及 QoS。独立作业批量运行可选数组任务；普通多进程任务按串行、线程、MPI 或混合模型规划。
2. 确认任务类型、总进程数、每进程线程数、节点数、**每节点**峰值内存、最长时间、远端脚本及工作目录。缺少并行模型、内存或时间时向用户提问；有历史日志可据此估算并说明依据。数组作业还需元素数和并发上限。用户关联多个 Slurm account 时询问计费账号并传 `--account`。
3. 运行 `cluster.py plan --kind ... --tasks ... --cpus-per-task ... --nodes ... --mem-gb ... --time DD-HH:MM:SS`。它按实时 QoS 限制选可容纳任务的 CPU 分区，并检查当前 CPU、内存及负载；`plan` 只读。
4. 在远端工作目录准备 `#!/bin/bash` 作业脚本，只写运行命令、必要的环境激活及显式输出路径。资源参数由 `cluster.py` 提交，不在脚本中写 `#SBATCH`。大任务先用真实输入的小样本做独立 Slurm 作业。
5. 紧接提交前运行 `submit`，它会重查资源并把作业限制在检查过的安全节点。默认要求当前安全节点能容纳任务。用户明确接受排队时才用 `--allow-queue`，任务仍需满足总容量和 QoS 限制。

格式示例；数值必须根据真实任务确定：

```bash
python3 <本技能目录>/scripts/cluster.py plan --kind threaded --tasks 1 --cpus-per-task 8 --nodes 1 --mem-gb 32 --time 02:00:00
python3 <本技能目录>/scripts/cluster.py submit --kind threaded --tasks 1 --cpus-per-task 8 --nodes 1 --mem-gb 32 --time 02:00:00 --script /home/USER/work/job.sh --workdir /home/USER/work
```

`--kind array` 还需 `--array-count N --max-parallel M`；CPU 和内存参数按**单个数组元素**填写。提交后报告 job ID、作业名、分区、QoS、资源、限制节点、工作目录、日志路径、监控状态文件和监控页面 URL。提交成功会自动启动本机独立轮询进程与汇总页面；详见 [monitoring.md](monitoring.md)。若返回 `monitor_error` 或 `dashboard_error`，作业仍可能已提交，必须保留 job ID 并报告错误。若 `sbatch` 响应超时，**不要直接重试**；先用 `cluster.py list` 按唯一作业名检查是否已提交。
