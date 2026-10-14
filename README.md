# XJTU_SCTS- 2136

本项目提供 `cluster-slurm` 技能，供 Codex、Claude Code 和 Trae 查询 CPU 集群实时资源、规划 QoS、通过 `sbatch` 提交作业，并在提交者电脑上监控。监控默认每 3 分钟查询一次；异常会尝试在本机显示带作业信息的提醒。

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
