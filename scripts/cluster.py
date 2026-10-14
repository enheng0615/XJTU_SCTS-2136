#!/usr/bin/env python3
"""Read-only cluster inventory, conservative CPU job planning, and guarded sbatch."""
import argparse
import json
import math
import re
import secrets
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from config import load as load_config, save as save_config, target as ssh_target

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ControlMaster=auto", "-o", "ControlPersist=30",
            "-o", "ControlPath=" + str(Path.home()/".ssh"/"cluster-slurm-%r@%h:%p")]
CPU_QOS = ("small", "medium", "long", "fat")


def remote(host, command, timeout=15):
    result = subprocess.run(["ssh", *SSH_OPTS, host, command], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"SSH/Slurm 查询失败: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def fields(line):
    return dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9/]*)=([^ ]+)", line))


def mb(value):
    if value == "0":
        return 0
    match = re.fullmatch(r"(\d+)([KMGT]?)", value, re.I)
    if not match:
        raise ValueError(f"无法解析内存请求: {value}")
    n, unit = int(match.group(1)), match.group(2).upper()
    return n * {"K": 1/1024, "M": 1, "G": 1024, "T": 1024*1024}[unit]


def hosts(expr):
    if re.fullmatch(r"[A-Za-z0-9._-]+", expr):
        return [expr]
    m = re.fullmatch(r"([A-Za-z0-9._-]+)\[([0-9,\-]+)\]", expr)
    if not m:
        raise ValueError(f"无法展开节点列表: {expr}")
    result = []
    for part in m.group(2).split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            if int(hi) < int(lo) or int(hi) - int(lo) > 1000:
                raise ValueError(f"节点范围异常: {part}")
            result.extend(f"{m.group(1)}{i:0{len(lo)}d}" for i in range(int(lo), int(hi)+1))
        else:
            result.append(m.group(1) + part)
    return result


def duration_minutes(value):
    m = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", value)
    if not m or int(m.group(3)) > 59 or int(m.group(4)) > 59 or (m.group(1) and int(m.group(2)) > 23):
        raise ValueError("时间格式必须为 HH:MM:SS 或 D-HH:MM:SS")
    return int(m.group(1) or 0)*1440 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/60


def qos_minutes(value):
    if value in ("", "UNLIMITED", "Partition_Limit"):
        return float("inf")
    return duration_minutes(value)


def inventory(host, settings):
    name = remote(host, "hostname")
    if name.split(".")[0] != settings["login_hostname"].split(".")[0]:
        raise RuntimeError(f"目标不是配置的登录节点 {settings['login_hostname']}: {name}")
    nodes_raw = remote(host, "scontrol show node -o")
    parts_raw = remote(host, "scontrol show partition -o")
    qos_raw = remote(host, "sacctmgr -n -P show qos format=Name,MaxWall,MaxTRESPerJob,MaxJobsPU,MaxSubmitJobsPU")
    assoc_raw = remote(host, "sacctmgr -n -P show assoc user=$(whoami) format=User,Account,Partition,QOS")
    jobs_raw = remote(host, 'squeue -h -t R -o "%N|%m"')
    partitions = {f.get("PartitionName"): f for line in parts_raw.splitlines() if (f := fields(line))}
    qos = {}
    for line in qos_raw.splitlines():
        cells = line.split("|")
        if len(cells) >= 5 and cells[0] in CPU_QOS:
            cpu = re.search(r"(?:^|,)cpu=(\d+)", cells[2])
            qos[cells[0]] = {"max_minutes": qos_minutes(cells[1]), "max_cpu": int(cpu.group(1)) if cpu else None,
                              "max_running": int(cells[3]) if cells[3].isdigit() else None,
                              "max_submitted": int(cells[4]) if cells[4].isdigit() else None}
    allowed = set()
    associations = {}
    for line in assoc_raw.splitlines():
        cells = line.split("|")
        if len(cells) >= 4:
            account = cells[1]
            if account:
                associations.setdefault(account, set()).update(cells[3].split(","))
                allowed.update(cells[3].split(","))
    reservations = {}
    unbounded = set()
    for line in jobs_raw.splitlines():
        try:
            expr, mem = line.split("|", 1)
            ns = hosts(expr)
            req = mb(mem)
            for n in ns:
                if req == 0: unbounded.add(n)
                else: reservations[n] = reservations.get(n, 0) + req
        except ValueError as e:
            raise RuntimeError(f"运行作业内存数据不明确，停止规划: {line}: {e}") from e
    node_names = []
    for line in nodes_raw.splitlines():
        f = fields(line)
        n = f.get("NodeName", "")
        if re.fullmatch(r"node\d+", n) and any(p in f.get("Partitions", "").split(",") for p in CPU_QOS):
            node_names.append(n)
    # Probe all compute nodes in one login-node SSH session. MemAvailable includes
    # reclaimable page cache, unlike Slurm's FreeMem field.
    probes = {}
    if node_names:
        loop = "for n in " + " ".join(shlex.quote(n) for n in node_names) + "; do printf '%s|' \"$n\"; ssh -o BatchMode=yes -o ConnectTimeout=2 \"$n\" \"grep '^MemAvailable:' /proc/meminfo\" 2>/dev/null || echo unavailable; done"
        try:
            for line in remote(host, loop, timeout=25).splitlines():
                n, _, value = line.partition("|")
                match = re.search(r"MemAvailable:\s+(\d+) kB", value)
                if match: probes[n] = int(match.group(1)) // 1024
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
    nodes = []
    for line in nodes_raw.splitlines():
        f = fields(line)
        n = f.get("NodeName", "")
        if not re.fullmatch(r"node\d+", n) or not any(p in f.get("Partitions", "").split(",") for p in CPU_QOS):
            continue
        total_cpu, allocated_cpu = int(f["CPUTot"]), int(f["CPUAlloc"])
        real_mem = int(f["RealMemory"])
        load = float(f.get("CPULoad", "0"))
        warnings = []
        if f.get("State", "").split("+")[0] not in ("IDLE", "MIXED"):
            warnings.append("节点状态不可用")
        if load - allocated_cpu > max(8, total_cpu*0.10):
            warnings.append("实际 CPU 负载明显高于 Slurm 分配")
        if n in unbounded:
            warnings.append("已有运行作业未请求内存")
        avail_mb = probes.get(n)
        if avail_mb is None:
            warnings.append("无法读取节点 MemAvailable")
        reserve_mb = max(16384, math.ceil(real_mem*0.10))
        safe_mem = max(0, min(real_mem - reservations.get(n, 0), avail_mb or 0) - reserve_mb)
        nodes.append({"name": n, "state": f.get("State"), "cpu_total": total_cpu, "cpu_slurm_free": total_cpu-allocated_cpu,
                      "cpu_load": load, "mem_total_gb": round(real_mem/1024, 1),
                      "mem_available_gb": round(avail_mb/1024, 1) if avail_mb is not None else None,
                      "mem_reserved_gb": round(reservations.get(n, 0)/1024, 1),
                      "mem_safe_new_gb": round(safe_mem/1024, 1) if not warnings else 0,
                      "warnings": warnings})
    if not nodes or not qos:
        raise RuntimeError("缺少 CPU 节点或 QoS 数据，停止规划")
    return {"host": host, "login_node": name, "checked_utc": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes, "qos": qos, "allowed_qos": sorted(allowed),
            "accounts": {k: sorted(v) for k, v in associations.items()}, "partitions": sorted(partitions)}


def plan(snapshot, args):
    tasks, cpt, count = args.tasks, args.cpus_per_task, args.nodes
    if min(tasks, cpt, count) < 1 or args.mem_gb <= 0:
        raise ValueError("进程、线程、节点和内存必须大于零")
    if tasks < count:
        raise ValueError("进程数不能少于节点数")
    if args.kind == "serial" and (tasks, cpt, count) != (1, 1, 1):
        raise ValueError("serial 必须为单进程、单线程、单节点")
    if args.kind == "threaded" and (tasks != 1 or count != 1):
        raise ValueError("threaded 必须为一个进程、一个节点")
    if args.kind == "mpi" and cpt != 1:
        raise ValueError("MPI 多线程任务请使用 hybrid")
    if args.kind == "array":
        if (tasks, count) != (1, 1) or not args.array_count or not args.max_parallel:
            raise ValueError("array 需要单进程单节点，以及 --array-count 和 --max-parallel")
        if args.array_count < 1 or not (1 <= args.max_parallel <= args.array_count):
            raise ValueError("数组数量或并发上限无效")
    elif args.array_count or args.max_parallel:
        raise ValueError("数组参数仅用于 array")
    minutes = duration_minutes(args.time)
    cpu = tasks*cpt
    accounts = snapshot.get("accounts", {})
    account = args.account
    if not account:
        if len(accounts) != 1:
            raise ValueError("当前账号关联多个或没有 Slurm account；请用 --account 指定并确认计费归属")
        account = next(iter(accounts))
    if account not in accounts:
        raise ValueError(f"当前用户未关联 Slurm account: {account}")
    chosen = None
    for q in CPU_QOS:
        limits = snapshot["qos"].get(q)
        if q in accounts[account] and q in snapshot["partitions"] and limits and limits["max_cpu"] and cpu <= limits["max_cpu"] and minutes <= limits["max_minutes"]:
            chosen = q
            break
    if not chosen:
        raise ValueError("任务超过当前账号可用 CPU QoS 的核心数或时限；请减小规模或联系管理员")
    if args.kind == "array" and snapshot["qos"][chosen]["max_submitted"] is not None and args.array_count > snapshot["qos"][chosen]["max_submitted"]:
        raise ValueError("数组元素数超过所选 QoS 的每用户最多提交任务数")
    per_node_cpu = math.ceil(tasks/count)*cpt
    candidates = [n for n in snapshot["nodes"] if not n["warnings"] and n["cpu_total"] >= per_node_cpu and n["mem_total_gb"] >= args.mem_gb + max(16, n["mem_total_gb"]*0.10)]
    now = [n for n in candidates if n["cpu_slurm_free"] >= per_node_cpu and n["mem_safe_new_gb"] >= args.mem_gb]
    now.sort(key=lambda n: (n["cpu_load"], -n["mem_safe_new_gb"]))
    if args.kind == "array":
        now = [n for n in now if n["cpu_slurm_free"] >= cpt*args.max_parallel and n["mem_safe_new_gb"] >= args.mem_gb*args.max_parallel]
    feasible_total = len(candidates) >= count
    immediate = len(now) >= count
    return {"kind": args.kind, "partition": chosen, "qos": chosen, "account": account,
            "total_cpus": cpu, "cpus_per_node": per_node_cpu,
            "mem_gb_per_node": args.mem_gb, "time": args.time, "nodes": count,
            "can_fit_total_capacity": feasible_total, "can_start_on_current_safe_nodes": immediate,
            "safe_nodes_now": [n["name"] for n in now], "eligible_nodes": [n["name"] for n in candidates],
            "excluded_nodes": {n["name"]: n["warnings"] for n in snapshot["nodes"] if n["warnings"]},
            "array_count": args.array_count if args.kind == "array" else None, "max_parallel": args.max_parallel if args.kind == "array" else None}


def submit(host, args, p):
    if not p["can_fit_total_capacity"]:
        raise RuntimeError("任务超过当前可用 CPU 节点的单节点容量")
    if not p["can_start_on_current_safe_nodes"] and not args.allow_queue:
        raise RuntimeError("当前没有足够的安全空闲资源；仅在用户明确接受排队时使用 --allow-queue")
    if args.kind == "array" and not p["can_start_on_current_safe_nodes"]:
        raise RuntimeError("数组任务的并发元素当前无法共同放入安全节点；请降低 --max-parallel 或稍后再试")
    selected = (p["safe_nodes_now"] if p["can_start_on_current_safe_nodes"] else p["eligible_nodes"])[:args.nodes]
    if len(selected) < args.nodes:
        raise RuntimeError("没有足够的安全候选节点")
    if not args.script.startswith("/") or not args.workdir.startswith("/") or "\n" in args.script + args.workdir:
        raise ValueError("--script 和 --workdir 必须是远端绝对路径")
    check = "test -f " + shlex.quote(args.script) + " -a -d " + shlex.quote(args.workdir)
    remote(host, check)
    size = remote(host, "stat -c %s -- " + shlex.quote(args.script))
    if not size.isdigit() or int(size) > 65536:
        raise ValueError("作业脚本过大或无法读取；请使用小于 64 KiB 的脚本")
    body = remote(host, "cat -- " + shlex.quote(args.script))
    if not body.startswith("#!"):
        raise ValueError("作业脚本需要 shebang，例如 #!/bin/bash")
    if re.search(r"^\s*#SBATCH\b", body, re.M):
        raise ValueError("作业脚本不能包含 #SBATCH 资源指令；请通过 cluster.py 参数统一指定")
    base_name = args.job_name or Path(args.script).stem
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", base_name):
        raise ValueError("--job-name 或脚本文件名只能包含字母、数字、下划线和横线，最长 32 字符")
    job_name = base_name + "-" + secrets.token_hex(4)
    cmd = ["sbatch", "--parsable", "--job-name="+job_name,
           "--account="+p["account"], "--partition="+p["partition"], "--qos="+p["qos"],
           "--nodes="+str(args.nodes), "--nodelist="+",".join(selected), "--ntasks="+str(args.tasks),
           "--ntasks-per-node="+str(math.ceil(args.tasks/args.nodes)), "--cpus-per-task="+str(args.cpus_per_task),
           "--mem="+str(math.ceil(args.mem_gb*1024))+"M", "--time="+args.time,
           "--chdir="+args.workdir, "--output="+args.workdir.rstrip("/")+"/slurm-%j.out"]
    if args.kind == "array":
        cmd.append(f"--array=0-{args.array_count-1}%{args.max_parallel}")
    cmd.append(args.script)
    try:
        result = remote(host, " ".join(shlex.quote(x) for x in cmd), timeout=20)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"sbatch 响应超时，作业可能已提交。不要重试；先用 cluster.py list 查找作业名 {job_name}") from exc
    if not re.fullmatch(r"\d+(?:;[^\n]+)?", result):
        raise RuntimeError(f"sbatch 未返回可识别 job ID: {result}")
    submission = {"job_id": result.split(";", 1)[0], "job_name": job_name, "nodes_restricted_to": selected,
                  "log_pattern": args.workdir.rstrip("/")+"/slurm-%j.out", "workdir": args.workdir}
    monitor_cmd = [sys.executable, str(Path(__file__).with_name("monitor.py")), "start", "--host", host,
                   "--job-id", submission["job_id"], "--job-name", job_name,
                   "--array-count", str(args.array_count if args.kind == "array" else 1),
                   "--interval", str(args.monitor_interval)]
    try:
        monitor = subprocess.run(monitor_cmd, capture_output=True, text=True, timeout=10)
        if monitor.returncode:
            submission["monitor_error"] = monitor.stderr.strip() or monitor.stdout.strip()
        else:
            submission["monitor"] = json.loads(monitor.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        # sbatch already accepted the job; report the ID even if local monitoring fails.
        submission["monitor_error"] = str(exc)
    dashboard_cmd = [sys.executable, str(Path(__file__).with_name("dashboard.py")),
                     "start", "--host", host, "--open-if-new"]
    try:
        dashboard = subprocess.run(dashboard_cmd, capture_output=True, text=True, timeout=10)
        if dashboard.returncode:
            submission["dashboard_error"] = dashboard.stderr.strip() or dashboard.stdout.strip()
        else:
            submission["dashboard"] = json.loads(dashboard.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        submission["dashboard_error"] = str(exc)
    return submission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["configure", "inspect", "plan", "submit", "status", "list"])
    parser.add_argument("--host", help="configure 使用的 SSH 主机/IP/别名")
    parser.add_argument("--ssh-user", help="configure 使用的 SSH 用户名")
    parser.add_argument("--login-hostname", help="configure 使用的登录节点 hostname")
    parser.add_argument("--account", help="多个 Slurm account 时明确指定计费账号")
    parser.add_argument("--kind", choices=["serial", "threaded", "mpi", "hybrid", "array"])
    parser.add_argument("--tasks", type=int)
    parser.add_argument("--cpus-per-task", type=int)
    parser.add_argument("--nodes", type=int)
    parser.add_argument("--mem-gb", type=float, help="每节点峰值内存，GiB")
    parser.add_argument("--time", help="HH:MM:SS 或 D-HH:MM:SS")
    parser.add_argument("--array-count", type=int)
    parser.add_argument("--max-parallel", type=int)
    parser.add_argument("--script", help="远端已有的作业脚本绝对路径")
    parser.add_argument("--workdir", help="远端工作目录绝对路径")
    parser.add_argument("--allow-queue", action="store_true")
    parser.add_argument("--job-id", help="status 使用的 Slurm job ID")
    parser.add_argument("--job-name", help="作业名前缀；提交时自动附加唯一标识")
    parser.add_argument("--monitor-interval", type=int, default=180, help="本机监控轮询间隔，秒；默认 180（3 分钟）")
    args = parser.parse_args()
    try:
        if args.action == "configure":
            path = save_config({"ssh_host": args.host, "ssh_user": args.ssh_user,
                                "login_hostname": args.login_hostname})
            print(json.dumps({"config_path": str(path), "configured": True}, ensure_ascii=False, indent=2))
            return
        settings = load_config()
        host = ssh_target(settings)
        if args.action == "list":
            queue = remote(host, 'squeue -h -u $(whoami) -o "%i|%j|%T|%P|%N|%R"')
            history = remote(host, 'sacct -n -P -u $(whoami) -S $(date -d "1 day ago" +%Y-%m-%d) --format=JobID,JobName,State,Submit')
            print(json.dumps({"queue": queue, "last_day": history}, ensure_ascii=False, indent=2))
            return
        if args.action == "status":
            if not args.job_id or not re.fullmatch(r"\d+", args.job_id):
                raise ValueError("status 需要数字 --job-id")
            queue = remote(host, "squeue -h -j " + args.job_id + ' -o "%i|%T|%P|%N|%R"')
            accounting = remote(host, "sacct -n -P -j " + args.job_id + " --format=JobID,State,Elapsed,AllocCPUS,ReqMem,NodeList,MaxRSS,ExitCode")
            print(json.dumps({"job_id": args.job_id, "queue": queue, "accounting": accounting}, ensure_ascii=False, indent=2))
            return
        if args.action != "inspect":
            if not 2 <= args.monitor_interval <= 3600:
                raise ValueError("--monitor-interval 必须在 2 到 3600 秒之间")
            required = ("kind", "tasks", "cpus_per_task", "nodes", "mem_gb", "time")
            missing = [k for k in required if getattr(args, k) is None]
            if missing: raise ValueError("缺少参数: " + ", ".join(missing))
        snap = inventory(host, settings)
        if args.action == "inspect": result = snap
        else:
            p = plan(snap, args)
            result = {"snapshot": snap, "plan": p}
            if args.action == "submit":
                if not args.script or not args.workdir: raise ValueError("submit 需要 --script 与 --workdir")
                result["submission"] = submit(host, args, p)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__": main()
