#!/usr/bin/env python3
"""Local, detached Slurm job monitor. Never runs a process on the login node."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from cluster import remote
from config import load as load_config, target as ssh_target

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
            "NODE_FAIL", "BOOT_FAIL", "PREEMPTED", "DEADLINE", "REVOKED"}


def now():
    return datetime.now(timezone.utc).isoformat()


def state_dir(host):
    safe_host = re.sub(r"[^A-Za-z0-9_.-]", "_", host)
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "cluster-slurm" / safe_host
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(base, 0o700)
    return base


def paths(host, job_id):
    base = state_dir(host)
    return base / f"{job_id}.json", base / f"{job_id}.log", base / f"{job_id}.stop"


def read_state(path):
    return json.loads(path.read_text()) if path.exists() else None


def save_state(path, data):
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def normal_state(value):
    return value.split()[0].split("+")[0].upper()


def notify(message):
    title = "Slurm 作业告警"
    if sys.platform == "darwin":
        # On some macOS setups, `display notification` returns 0 but only opens
        # an empty Script Editor window. A Finder dialog exposes the actual
        # failure text, and a detached helper keeps the poller responsive.
        cmd = ["osascript", "-e", "on run argv", "-e",
               'tell application "Finder"', "-e", "activate", "-e",
               'display dialog (item 1 of argv) with title (item 2 of argv) '
               'buttons {"确定"} default button "确定" with icon caution giving up after 60',
               "-e", "end tell", "-e", "end run", message, title]
        try:
            child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            time.sleep(0.2)
            if child.poll() not in (None, 0):
                return {"method": "finder_dialog", "requested": False,
                        "error": f"Finder 提醒进程退出码 {child.returncode}"}
            return {"method": "finder_dialog", "requested": True, "error": None,
                    "helper_pid": child.pid}
        except OSError as exc:
            return {"method": "finder_dialog", "requested": False, "error": str(exc)}
    elif sys.platform.startswith("linux"):
        cmd = ["notify-send", title, message]
    else:
        return {"method": "none", "requested": False, "error": "当前系统不支持桌面通知"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        error = None if result.returncode == 0 else (result.stderr.strip() or "系统通知命令失败")
    except (OSError, subprocess.TimeoutExpired) as exc:
        error = str(exc)
    return {"method": "notify-send", "requested": error is None, "error": error}


def alert(data, message):
    notification = notify(message)
    data.setdefault("alerts", []).append({"at_utc": now(), "message": message,
                                            "notification": notification})
    data["alerts"] = data["alerts"][-50:]


def poll(host, job_id, expected):
    try:
        queue = remote(host, "squeue -h -j " + job_id + ' -o "%i|%T|%N|%R"')
    except RuntimeError as exc:
        # Slurm may remove a finished job from squeue before sacct is queried.
        if "Invalid job id specified" not in str(exc):
            raise
        queue = ""
    accounting = remote(host, "sacct -n -P -X -j " + job_id + " --format=JobIDRaw,State,Elapsed,NodeList,ExitCode")
    queue_rows = [line.split("|", 3) for line in queue.splitlines() if line]
    entries = []
    for line in accounting.splitlines():
        cells = line.split("|")
        if len(cells) < 5:
            continue
        identity = cells[0]
        if identity == job_id or re.fullmatch(re.escape(job_id) + r"_\d+", identity):
            entries.append({"id": identity, "state": normal_state(cells[1]),
                            "elapsed": cells[2], "nodes": cells[3], "exit_code": cells[4]})
    task_rows = [x for x in entries if re.fullmatch(re.escape(job_id) + r"_\d+", x["id"])] if expected > 1 else [x for x in entries if x["id"] == job_id]
    counts = dict(Counter(x["state"] for x in task_rows))
    running = [x for x in queue_rows if len(x) >= 2 and normal_state(x[1]) == "RUNNING"]
    if queue_rows:
        phase = "RUNNING" if running else "PENDING"
    elif len(task_rows) >= expected and all(x["state"] in TERMINAL for x in task_rows):
        phase = "COMPLETED" if all(x["state"] == "COMPLETED" for x in task_rows) else "FAILED"
    else:
        phase = "ACCOUNTING_PENDING"
    nodes = sorted({x["nodes"] for x in task_rows if x["nodes"] not in ("", "None", "Unknown")})
    failed_samples = [x for x in task_rows if x["state"] in TERMINAL and x["state"] != "COMPLETED"][:3]
    return {"phase": phase, "state_counts": counts, "accounted_tasks": len(task_rows),
            "expected_tasks": expected, "queue_tasks": len(queue_rows), "nodes": nodes,
            "tasks": task_rows[:100], "failed_samples": failed_samples, "queue": queue_rows[:100]}


def worker(args):
    if args.ready_fd is not None:
        try:
            os.read(args.ready_fd, 1)
        finally:
            os.close(args.ready_fd)
    state_path, log_path, stop_path = paths(args.host, args.job_id)
    data = read_state(state_path) or {}
    data.update({"job_id": args.job_id, "host": args.host, "job_name": args.job_name,
                 "expected_tasks": args.array_count, "interval_seconds": args.interval,
                 "monitor_pid": os.getpid()})
    previous = data.get("phase")
    failures = 0
    while True:
        if stop_path.exists():
            data.update({"phase": "MONITOR_STOPPED", "last_checked_utc": now()})
            save_state(state_path, data)
            stop_path.unlink(missing_ok=True)
            return
        try:
            result = poll(args.host, args.job_id, args.array_count)
            data.update(result)
            data["last_checked_utc"] = now()
            data.pop("last_error", None)
            data.pop("consecutive_poll_errors", None)
            failures = 0
            bad = sum(count for state, count in data["state_counts"].items() if state in TERMINAL and state != "COMPLETED")
            if bad > data.get("alerted_failed_tasks", 0):
                details = "; ".join(f"{x['id']}: {x['state']}，退出码 {x['exit_code']}，节点 {x['nodes']}"
                                    for x in data["failed_samples"])
                message = f"作业 {args.job_id} 有 {bad} 个任务异常结束。"
                if details:
                    message += "\n" + details
                message += f"\n可在 AI 中查询作业 {args.job_id} 的详细状态。"
                alert(data, message)
                data["alerted_failed_tasks"] = bad
            abnormal_queue = sorted({normal_state(x[1]) for x in data["queue"] if len(x) >= 2
                                     and normal_state(x[1]) not in ("PENDING", "RUNNING", "CONFIGURING", "COMPLETING")})
            signature = ",".join(abnormal_queue)
            if signature and signature != data.get("alerted_queue_state"):
                alert(data, f"作业 {args.job_id} 队列状态异常：{signature}。")
            data["alerted_queue_state"] = signature
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            failures += 1
            data["last_error"] = str(exc)
            data["last_checked_utc"] = now()
            data["consecutive_poll_errors"] = failures
            if failures == 1:
                alert(data, f"作业 {args.job_id} 监控查询失败：{str(exc)[:160]}")
        if data.get("phase") != previous:
            data.setdefault("transitions", []).append({"at_utc": now(), "phase": data.get("phase")})
            data["transitions"] = data["transitions"][-100:]
            previous = data.get("phase")
        save_state(state_path, data)
        if data.get("phase") in ("COMPLETED", "FAILED") and "last_error" not in data:
            return
        delay = min(300, args.interval * (2 ** min(failures, 3))) if failures else args.interval
        time.sleep(delay)


def start(args):
    state_path, log_path, stop_path = paths(args.host, args.job_id)
    existing = read_state(state_path)
    args.array_count = args.array_count or (existing.get("expected_tasks") if existing else None) or 1
    args.interval = args.interval or (existing.get("interval_seconds") if existing else None) or 180
    args.job_name = args.job_name or (existing.get("job_name") if existing else "")
    if existing and existing.get("phase") not in ("COMPLETED", "FAILED", "MONITOR_STOPPED") and alive(existing.get("monitor_pid")):
        return {"monitor_pid": existing["monitor_pid"], "state_file": str(state_path), "already_running": True}
    stop_path.unlink(missing_ok=True)
    initial = dict(existing or {})
    initial.update({"job_id": args.job_id, "host": args.host, "job_name": args.job_name,
                    "phase": "STARTING", "expected_tasks": args.array_count,
                    "interval_seconds": args.interval})
    initial.setdefault("submitted_at_utc", now())
    initial.setdefault("transitions", [])
    save_state(state_path, initial)
    cmd = [sys.executable, str(Path(__file__).resolve()), "run", "--host", args.host,
           "--job-id", args.job_id, "--job-name", args.job_name,
           "--array-count", str(args.array_count), "--interval", str(args.interval)]
    ready_read, ready_write = os.pipe()
    cmd.extend(["--ready-fd", str(ready_read)])
    try:
        with log_path.open("a") as log:
            os.chmod(log_path, 0o600)
            child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True, close_fds=True, pass_fds=(ready_read,))
        os.close(ready_read)
        initial["monitor_pid"] = child.pid
        save_state(state_path, initial)
        os.write(ready_write, b"1")
    finally:
        try: os.close(ready_read)
        except OSError: pass
        os.close(ready_write)
    return {"monitor_pid": child.pid, "state_file": str(state_path), "log_file": str(log_path),
            "poll_interval_seconds": args.interval}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "run", "show", "stop"])
    parser.add_argument("--host", help="内部调用使用；默认读取本机集群配置")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--job-name", default="")
    parser.add_argument("--array-count", type=int)
    parser.add_argument("--interval", type=int, help="轮询间隔秒数；默认 180（3 分钟）")
    parser.add_argument("--ready-fd", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.host is None:
        try:
            args.host = ssh_target(load_config())
        except (RuntimeError, ValueError) as exc:
            parser.error(str(exc))
    if not re.fullmatch(r"\d+", args.job_id) or (args.array_count is not None and args.array_count < 1) or (args.interval is not None and not 2 <= args.interval <= 3600):
        parser.error("job ID、数组元素数或轮询间隔无效")
    if args.action == "start":
        print(json.dumps(start(args), ensure_ascii=False, indent=2))
    elif args.action == "run":
        worker(args)
    else:
        state_path, _, stop_path = paths(args.host, args.job_id)
        data = read_state(state_path)
        if not data:
            parser.error("没有找到此作业的本机监控记录")
        if args.action == "stop":
            stop_path.touch(mode=0o600)
            data["stop_requested"] = True
        data["monitor_alive"] = alive(data.get("monitor_pid"))
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
