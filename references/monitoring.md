# 本机持续监控

`submit` 为每个 Slurm 作业启动一个独立的本机轮询进程，默认每 180 秒查询一次；用户可用 `--monitor-interval 秒数` 设置 2–3600 秒。多个普通作业和作业数组共用一个本机监控页面；页面每 3 秒读取本机状态文件并显示阶段、数组完成数、节点、上次查询时间、进程健康及异常详情。页面刷新频率不会增加对集群的查询频率。首次提交会在默认浏览器打开页面；后续提交复用现有页面。支持浏览器侧栏的 Agent 可在侧栏打开 `submission.dashboard.url`；其他 Agent 可展示该本机 URL。

本机命令：

```bash
python3 <本技能目录>/scripts/dashboard.py open
python3 <本技能目录>/scripts/dashboard.py status
python3 <本技能目录>/scripts/dashboard.py stop
python3 <本技能目录>/scripts/monitor.py show --job-id ID
python3 <本技能目录>/scripts/monitor.py start --job-id ID
python3 <本技能目录>/scripts/monitor.py stop --job-id ID
```

`dashboard.py stop` 只关闭页面服务；`monitor.py stop` 只停止指定作业的本机轮询。两者都不会取消 Slurm 作业。作业结束后轮询进程退出，页面仍能显示历史记录。页面服务仅绑定本机 `127.0.0.1`，读取本机状态文件，不在登录节点运行。

监控记录排队、运行和终态。失败、取消、超时、OOM、异常队列状态或查询失败会写入状态文件，并尝试本机告警；页面中的异常卡片持续显示原因、退出码和节点。macOS 使用 Finder 对话框，Linux 使用 `notify-send`。`notification.requested` 只说明发起了系统提醒，不能证明用户看到。状态保存在 `~/.local/state/cluster-slurm/<主机>/<job-id>.json`（或 `XDG_STATE_HOME` 下）。

Agent 会话若仍在等待作业结果，应按轮询间隔用 `monitor.py show` 核对，并在发现异常时在会话内报告。会话结束后，独立页面和本机提醒继续工作，但无法自动向已结束的 AI 会话发送消息。电脑睡眠、关机或断网时无法持续查询；恢复后可用 `monitor.py start --job-id ID` 重新附着。告警发现时间取决于轮询间隔，SSH 失败时会退避，最终状态以 Slurm 为准。
