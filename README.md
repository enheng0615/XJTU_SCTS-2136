# XJTU_SCTS- 2136

本项目提供 `cluster-slurm` 技能，供 Codex、Claude Code 和 Trae 查询 CPU 集群实时资源、规划 QoS、通过 `sbatch` 提交作业，并在提交者电脑上监控。每个作业有独立的本机轮询进程；用户可选择是否开启多个作业共用的本机监控页面。默认每 3 分钟查询一次 Slurm，页面每 3 秒更新显示；异常会记录在本机状态文件，并尝试本机提醒。

## 我的建议是直接把这个github网址给agent让他给你部署，如果你有兴趣（足够犟）你也可以按照下面的安装步骤进行安装。欢迎一起维护

## 安装

下载 Release 中的 **Source code (zip)**，解压后进入生成的 `XJTU_SCTS-2136-*` 目录运行：

```bash
python3 install.py --platform all
```

也可把 `all` 换成 `codex`、`claude` 或 `trae`。

## 新用户配置服务器与账号

向集群管理员取得三个值：`HOST`（登录节点 IP、域名或自己的 SSH 别名）、`USER`（**集群 Linux 用户名，不是 GitHub 用户名**）、`NAME`（登录节点运行 `hostname` 后返回的名称）。把以下 `USER`、`HOST` 换成自己的值，先在**自己的普通终端**验证 SSH 密钥或其他获准的非交互认证：

```bash
ssh -o BatchMode=yes USER@HOST hostname
```

该命令只查询登录节点名称；把输出作为 `NAME`。若它要求输入密码或连接失败，先按管理员提供的方式配置本机 `~/.ssh/config` 和 SSH 密钥。技能包不接收、不保存密码或私钥。然后运行：

```bash
python3 ~/.codex/skills/cluster-slurm/scripts/cluster.py configure --host HOST --ssh-user USER --login-hostname NAME
python3 ~/.codex/skills/cluster-slurm/scripts/cluster.py inspect
```

Claude Code、Trae 用户将 `~/.codex/skills` 分别换为 `~/.claude/skills`、`~/.trae-cn/skills`。`configure` 会在本机创建 `~/.config/cluster-slurm/config.json`，仅保存这三个非密钥字段；`inspect` 会验证连接、登录节点身份并读取实时资源。多个 Slurm 计费账号不在这里配置，提交具体作业时按需传 `--account`。

完整说明见 [INSTALL.md](INSTALL.md)。此版本保留本组 CPU 节点命名规则以及 `small`、`medium`、`long`、`fat` 的 QoS/分区映射；其他集群需要调整这部分规则。不要在登录节点直接运行计算程序。

## 监控页面与轮询间隔

提交成功后，每个作业（包括数组作业）会在**提交者电脑**上启动一个独立监控进程，定时通过 SSH 查询 Slurm。可选的页面汇总本机记录，显示作业阶段、数组任务数量、节点、上次服务器查询时间、轮询进程状态和异常详情。页面绑定 `127.0.0.1`，每 3 秒读取一次本机记录；这 3 秒只是**页面刷新频率**，不会每 3 秒查询服务器。默认服务器查询间隔为 **180 秒（3 分钟）**。关掉页面或浏览器窗口不会取消 Slurm 作业，也不会停止独立监控进程及异常提醒。电脑睡眠、断网或关机期间无法查询；已结束的 AI 对话不会被监控进程自动唤醒。

以下以 Codex 安装目录为例；Claude Code 和 Trae 用户把 `~/.codex/skills` 分别换成 `~/.claude/skills`、`~/.trae-cn/skills`。

| 目的 | 本机命令 |
| --- | --- |
| 查看页面开关、运行状态及地址 | `python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py status` |
| 关闭自动打开页面，并停止当前页面服务 | `python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py disable` |
| 开启以后提交时自动打开页面 | `python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py enable` |
| 立即手动打开一次页面，不改变开关 | `python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py open` |
| 仅关闭当前页面服务，保留自动打开设置 | `python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py stop` |

页面开关默认开启，保存在本机 `~/.config/cluster-slurm/preferences.json`（或 `CLUSTER_SLURM_PREFERENCES` 指定的位置）。`enable` 只保存设置，**不会立刻弹出页面**；如需立刻查看，再运行 `open`。`disable` 会停止当前页面服务，但各作业的轮询进程继续工作；`stop` 是临时关闭，下次提交仍按开关设置自动打开。`status` 可用于调试：查看 `dashboard_enabled`、`running` 和当前 `url`。若页面打不开，查看本机 `~/.local/state/cluster-slurm/<主机>/dashboard.log`。`open` 可在开关关闭时临时查看，不会改动默认设置。

提交时可在原有 `cluster.py submit ...` 命令后加 `--no-dashboard`，仅本次不自动启动页面；加 `--dashboard` 则仅本次启动页面，覆盖本机默认设置。已有共用页面如果仍在运行，仍会显示此作业；要关掉现有页面请运行 `dashboard.py disable`。无论选哪个参数，提交后的独立作业监控都会启动。

修改 **Slurm 查询间隔**：在原有 `cluster.py submit` 命令末尾加 `--monitor-interval 60`，即可让新作业每 60 秒查询一次。已提交作业使用下面的命令，替换其中的真实 job ID：

```bash
python3 ~/.codex/skills/cluster-slurm/scripts/monitor.py interval --job-id 123456 --interval 60
python3 ~/.codex/skills/cluster-slurm/scripts/monitor.py show --job-id 123456
```

间隔单位为秒，允许 `2`–`3600`；提交时不指定就是 `180`。`monitor.py interval` 通常在 3 秒内被运行中的本机进程读到；若网络查询刚在进行，则在该次查询结束后生效。更短的间隔会增加 SSH/Slurm 查询频率；查询失败时监控会退避，最长间隔 5 分钟。页面刷新固定为 3 秒，与上述间隔独立。
