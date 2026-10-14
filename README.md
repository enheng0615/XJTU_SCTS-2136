# cluster-slurm

供 Codex、Claude Code 和 Trae 使用的 CPU/Slurm 作业技能：查询实时资源、规划 QoS、通过 `sbatch` 提交，并在提交者电脑上监控作业。监控默认每 3 分钟查询一次；异常会尝试发送本机系统通知。

## 安装

下载 Release 中的 `cluster-slurm.zip`，解压后在 `cluster-slurm` 目录运行：

```bash
python3 install.py --platform all
```

也可把 `all` 换成 `codex`、`claude` 或 `trae`。然后在已安装的技能中设置**自己的** SSH 地址、账号和登录节点名称：

```bash
python3 ~/.codex/skills/cluster-slurm/scripts/cluster.py configure --host HOST --ssh-user USER --login-hostname NAME
python3 ~/.codex/skills/cluster-slurm/scripts/cluster.py inspect
```

Claude Code、Trae 用户将 `~/.codex/skills` 分别换为 `~/.claude/skills`、`~/.trae-cn/skills`。`HOST` 是登录节点的 IP、域名或 SSH 别名；`USER` 是个人 SSH 用户名；`NAME` 是登录节点上 `hostname` 的结果。配置保存在本机 `~/.config/cluster-slurm/config.json`，不会写入下载的技能目录。SSH 认证仍由用户自己的 SSH 配置和密钥提供。

完整说明见 [INSTALL.md](INSTALL.md)。此版本保留本组 CPU 节点命名规则以及 `small`、`medium`、`long`、`fat` 的 QoS/分区映射；其他集群需要调整这部分规则。不要在登录节点直接运行计算程序。
