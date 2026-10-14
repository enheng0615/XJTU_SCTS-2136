# XJTU_SCTS- 2136：安装与使用

需要本机能以 SSH 非交互方式连接集群；技能包不包含服务器地址、个人账号或密钥。macOS/Linux 安装：

```bash
python3 install.py --platform all
```

也可只安装 `codex`、`claude` 或 `trae`。安装器把同一个 `SKILL.md` 放入各工具的用户级技能目录，把 `PreToolUse` hook 合并进各自配置，并备份已有配置。Codex 的非托管 hook 需要在 `/hooks` 中审阅并信任。Trae 需在设置中启用 Hook 的本地运行方式。新会话会发现技能；在对话中也可明确说“使用 cluster-slurm 技能提交”。

## 首次配置自己的集群连接

向管理员取得登录节点地址或 SSH 别名 `HOST`、个人**集群 Linux 用户名** `USER`，并确认自己获准登录。`USER` 不是 GitHub 用户名。技能不会配置 SSH 密码、私钥或双因素认证；这些仍由每个人按集群规定放在自己的 SSH 环境中。

在用户自己的普通终端做一个只读连接检查：

```bash
ssh -o BatchMode=yes USER@HOST hostname
```

把输出作为 `NAME`。它是远端登录节点的真实 `hostname`，可能不同于连接用的域名、IP 或 SSH 别名。若这一步提示密码、双因素认证或失败，先按管理员指引配置非交互 SSH 认证；不要把密码或私钥写进技能或传给 AI。用户可以在 `~/.ssh/config` 中配置自己的 `Host`、`HostName`、`IdentityFile` 等，`--host` 则填写该 `Host` 别名。

把三个占位符替换成自己的值，然后配置并验证：

```bash
python3 ~/.codex/skills/cluster-slurm/scripts/cluster.py configure --host HOST --ssh-user USER --login-hostname NAME
python3 ~/.codex/skills/cluster-slurm/scripts/cluster.py inspect
```

Claude Code 或 Trae 用户把路径换为 `~/.claude/skills` 或 `~/.trae-cn/skills`。`configure` 返回 `configured: true` 和配置路径；`inspect` 成功时输出节点、分区、QoS 和实时剩余资源。若提示登录节点名称不符，重新核对 `NAME` 与远端 `hostname`，不要跳过身份检查。本机配置保存在 `~/.config/cluster-slurm/config.json`，权限为仅当前用户可读写，不应上传到仓库。三个字段是 `ssh_host`、`ssh_user`、`login_hostname`；换账号或地址时重新运行 `configure` 即可。多个 Slurm 计费账号不保存在这份配置中，需要提交作业时用 `--account` 选择。

若本机通过 SSH 别名连接集群，hook 会读取 `~/.ssh/config` 并识别该别名及其目标地址；其他入口可在 AI 工具的启动环境设置 `CLUSTER_SSH_HOSTS=别名1,别名2`。

本 hook 只拦截 AI 终端工具中显式出现的 `ssh` 登录节点命令。它不能防住 Python 间接调用、其他协议、手工终端、代理跳转或所有工具路径，也无法在 hook 超时/失效时保证阻断。要彻底防止管理节点被占满，管理员还需在服务器端给登录节点设置用户进程的 CPU/内存上限和审计。技能中的资源快照也不是 Slurm 的资源预留，提交前会重新读取。

节点命名规则 `node[0-9]+` 和 CPU 分区/QoS `small`、`medium`、`long`、`fat` 保留在技能中，适用于本组集群。资源参数格式见 `SKILL.md`。在任意平台，若用户未给每节点峰值内存、时间和并行方式，AI 应先问清楚，再提交。

## 提交后的本机监控

`submit` 成功后为每个作业自动启动独立的本机轮询进程；页面开关默认开启，会启动一个所有作业共用的本机监控页面。第一次提交时在默认浏览器打开；以后提交的普通作业和作业数组自动加入同一页面，不会重复创建窗口。启用页面时，`submit` 的 JSON 输出包含 `submission.dashboard.url`，支持浏览器侧栏的 Agent 可以在侧栏打开这个地址。页面每 3 秒读取本机状态文件；默认每 3 分钟（180 秒）才查询一次 Slurm。提交时可传 `--monitor-interval 30` 调整服务器查询为 30 秒（允许 2–3600 秒）；运行中的作业可用 `monitor.py interval --job-id ID --interval 30` 修改。页面会显示作业阶段、数组完成数量、节点、上次查询时间、监控进程状态、失败原因和退出码。

异常发生后会在下一次查询时显示在页面上，并尝试本机提醒：macOS 使用带详细文字的 Finder 对话框（60 秒后自动关闭），Linux 使用 `notify-send`。告警及提醒请求结果写入状态文件；`notification.requested` 不代表用户一定看到了提醒。查询失败会退避重试，最多每 5 分钟一次。监控和页面服务都只在提交者电脑上运行，不占用服务器登录节点。

```bash
python3 ~/.codex/skills/cluster-slurm/scripts/monitor.py show --job-id 123456
python3 ~/.codex/skills/cluster-slurm/scripts/monitor.py interval --job-id 123456 --interval 60
python3 ~/.codex/skills/cluster-slurm/scripts/monitor.py start --job-id 123456
python3 ~/.codex/skills/cluster-slurm/scripts/monitor.py stop --job-id 123456
python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py open
python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py status
python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py disable
python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py enable
python3 ~/.codex/skills/cluster-slurm/scripts/dashboard.py stop
```

`monitor.py show` 查看本机记录，`interval` 调整已有作业的轮询间隔，`start` 可在监控意外退出后重新附着，`stop` 只停止指定作业的本机轮询。`dashboard.py status` 返回 `dashboard_enabled`、`running` 与页面地址；`disable` 关闭以后提交时的自动页面并停止当前页面，`enable` 保存开启设置，`open` 立即手动打开页面但不更改开关，`stop` 只临时关闭页面服务。原有 `cluster.py submit` 命令末尾可加 `--dashboard` 或 `--no-dashboard` 临时覆盖；若共用页面已运行，`--no-dashboard` 仍会让作业出现在页面中。这些命令都不会取消 Slurm 作业，也不会因为关闭页面而停止独立监控进程。作业完成后，页面仍显示历史记录。状态记录在 `~/.local/state/cluster-slurm/<主机>/<job-id>.json`，也可通过 `XDG_STATE_HOME` 修改位置。页面开关保存在 `~/.config/cluster-slurm/preferences.json`，也可通过 `CLUSTER_SLURM_PREFERENCES` 指定位置。电脑睡眠、关机或断网时，进程无法及时发现异常；系统通知若被禁用，状态文件仍会保存检测结果。已结束的 AI 对话不会因桌面通知自动重新打开。
