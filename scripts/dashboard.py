#!/usr/bin/env python3
"""Local, read-only dashboard for one or many detached Slurm job monitors."""
import argparse
import fcntl
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import load as load_config, load_dashboard_enabled, save_dashboard_enabled, target as ssh_target
from monitor import alive, read_state, save_state, state_dir

HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Slurm 作业监控</title><style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172235;background:#f4f7fb}
body{max-width:1120px;margin:0 auto;padding:28px 20px}h1{font-size:25px;margin:0 0 8px}
.muted{color:#607088}.top{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:24px}
.pill{border-radius:999px;padding:6px 11px;background:#e7eef8;color:#264b78;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px}
.card{background:white;border:1px solid #dbe4ef;border-radius:14px;padding:18px;box-shadow:0 3px 12px #152a4110}
.card.bad{border-color:#ee9a9a;background:#fff9f9}.card.done{border-color:#a6d8bc}
.title{display:flex;justify-content:space-between;align-items:center;gap:12px}.title strong{font-size:19px}
.phase{font-weight:700;color:#265f9c}.bad .phase{color:#aa2639}.done .phase{color:#218352}
.name{font-size:14px;color:#607088;overflow-wrap:anywhere;margin-top:3px}
.row{display:flex;justify-content:space-between;gap:10px;padding-top:10px;font-size:14px}
.row span:last-child{text-align:right;overflow-wrap:anywhere}.alert{white-space:pre-wrap;background:#fff0f1;border-radius:8px;padding:10px;margin-top:13px;font-size:13px;color:#91293a}
.empty{padding:38px;text-align:center;background:white;border:1px dashed #bbc9da;border-radius:14px;color:#607088}
</style></head><body>
<div class="top"><div><h1>Slurm 作业监控</h1><div class="muted" id="host">正在读取本机监控记录…</div></div><span class="pill" id="updated">每 3 秒刷新显示</span></div>
<div id="jobs" class="grid"></div>
<p class="muted">此页面只读取本机状态文件；服务器查询间隔由各作业的监控参数决定。关闭页面不会停止监控。</p>
<script>
const token=location.pathname.split('/')[1], jobs=document.getElementById('jobs');
function row(card,label,value){let d=document.createElement('div');d.className='row';let a=document.createElement('span'),b=document.createElement('span');a.textContent=label;b.textContent=value;d.append(a,b);card.append(d)}
function fmt(t){if(!t)return '等待首次查询';let d=new Date(t);return Number.isNaN(d.getTime())?t:d.toLocaleString()}
function draw(data){document.getElementById('host').textContent='集群连接：'+data.host+' · 共 '+data.jobs.length+' 个作业记录';
document.getElementById('updated').textContent='页面刷新 '+new Date().toLocaleTimeString();jobs.replaceChildren();
if(!data.jobs.length){let e=document.createElement('div');e.className='empty';e.textContent='尚无本机监控作业。提交后会自动出现在这里。';jobs.append(e);return}
for(const j of data.jobs){let c=document.createElement('section');c.className='card'+(j.problem?' bad':j.phase==='COMPLETED'?' done':'');
let t=document.createElement('div');t.className='title';let id=document.createElement('strong');id.textContent='#'+j.job_id;let p=document.createElement('span');p.className='phase';p.textContent=j.phase||'STARTING';t.append(id,p);c.append(t);
let n=document.createElement('div');n.className='name';n.textContent=j.job_name||'未命名作业';c.append(n);
row(c,'任务进度',j.expected_tasks>1?j.accounted_tasks+'/'+j.expected_tasks+' 已计入 · '+Object.entries(j.state_counts||{}).map(([s,v])=>s+' '+v).join(' / '):'单任务');
row(c,'节点',(j.nodes||[]).join(', ')||'尚未分配');row(c,'上次服务器查询',fmt(j.last_checked_utc));
row(c,'查询间隔',(j.interval_seconds||180)+' 秒');row(c,'监控进程',j.monitor_alive?'运行中':j.terminal?'已结束':'未运行');
if(j.failed_samples?.length)row(c,'异常退出码',j.failed_samples.map(x=>x.id+': '+x.exit_code).join('; '));
let msg=j.last_error||(j.alerts?.length?j.alerts[j.alerts.length-1].message:'');
if(j.problem&&msg){let a=document.createElement('div');a.className='alert';a.textContent=msg;c.append(a)}jobs.append(c)} }
async function refresh(){try{let r=await fetch('/'+token+'/api',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);draw(await r.json())}
catch(e){document.getElementById('updated').textContent='读取失败：'+e.message}}
refresh();setInterval(refresh,3000);
</script></body></html>"""


def registry_path(host):
    return state_dir(host) / "dashboard.json"


def ping(info):
    try:
        url = f"http://127.0.0.1:{info['port']}/{info['token']}/health"
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return response.read() == b"ok"
    except (KeyError, ValueError, OSError, urllib.error.URLError):
        return False


def current(host):
    try:
        info = read_state(registry_path(host))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) and ping(info) else None


def public_info(info):
    return {"dashboard_pid": info["pid"], "url": f"http://127.0.0.1:{info['port']}/{info['token']}/",
            "state_file": str(info["state_file"])}


def start(host, open_window=False, only_if_created=False):
    base = state_dir(host)
    lock = base / "dashboard.lock"
    with lock.open("a") as lock_file:
        os.chmod(lock, 0o600)
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        info = current(host)
        created = False
        if info is None:
            registry_path(host).unlink(missing_ok=True)
            cmd = [sys.executable, str(Path(__file__).resolve()), "serve", "--host", host]
            log_path = base / "dashboard.log"
            with log_path.open("a") as log:
                os.chmod(log_path, 0o600)
                child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         start_new_session=True)
            for _ in range(50):
                time.sleep(0.1)
                info = current(host)
                if info is not None:
                    created = True
                    break
                if child.poll() is not None:
                    break
            if info is None:
                raise RuntimeError(f"本机监控页面未启动；查看 {log_path}")
        result = public_info(info)
        result["already_running"] = not created
    if open_window and (created or not only_if_created):
        try:
            result["window_open_requested"] = bool(webbrowser.open_new_tab(result["url"]))
        except Exception as exc:
            result["window_open_requested"] = False
            result["window_error"] = str(exc)
    return result


def jobs(host):
    rows = []
    for path in state_dir(host).glob("[0-9]*.json"):
        if not re.fullmatch(r"\d+\.json", path.name):
            continue
        try:
            data = read_state(path)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        phase = data.get("phase", "STARTING")
        terminal = phase in ("COMPLETED", "FAILED", "MONITOR_STOPPED")
        data["monitor_alive"] = alive(data.get("monitor_pid")) if not terminal else False
        data["terminal"] = terminal
        data["problem"] = bool(data.get("last_error") or data.get("failed_samples")
                               or phase in ("FAILED", "MONITOR_STOPPED")
                               or (not terminal and not data["monitor_alive"] and phase != "STARTING"))
        rows.append(data)
    rows.sort(key=lambda d: d.get("submitted_at_utc", ""), reverse=True)
    rows.sort(key=lambda d: d.get("terminal", False))
    return rows[:100]


def serve(host):
    token = secrets.token_urlsafe(24)
    registry = registry_path(host)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in (f"/{token}/", f"/{token}/api", f"/{token}/health"):
                self.send_error(404)
                return
            if self.path.endswith("/health"):
                body, mime = b"ok", "text/plain"
            elif self.path.endswith("/api"):
                body = json.dumps({"host": host, "jobs": jobs(host)}, ensure_ascii=False).encode()
                mime = "application/json; charset=utf-8"
            else:
                body, mime = HTML.encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    info = {"pid": os.getpid(), "port": server.server_port, "token": token,
            "state_file": str(registry), "host": host}
    save_state(registry, info)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        saved = read_state(registry)
        if saved and saved.get("pid") == os.getpid():
            registry.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["enable", "disable", "start", "open", "status", "stop", "serve"])
    parser.add_argument("--host", help="内部调用使用；默认读取本机集群配置")
    parser.add_argument("--open-if-new", action="store_true", help="首次启动时打开浏览器；后续提交复用窗口")
    args = parser.parse_args()
    try:
        if args.action == "enable":
            save_dashboard_enabled(True)
            print(json.dumps({"dashboard_enabled": True, "preferences_saved": True,
                              "next_submit_auto_opens": True}, ensure_ascii=False, indent=2))
            return
        if args.action == "disable":
            save_dashboard_enabled(False)
            try:
                host = args.host or ssh_target(load_config())
            except (RuntimeError, ValueError):
                print(json.dumps({"dashboard_enabled": False, "preferences_saved": True,
                                  "running": False, "job_monitors_unaffected": True}, ensure_ascii=False, indent=2))
                return
            info = current(host)
            if info:
                os.kill(info["pid"], signal.SIGTERM)
            print(json.dumps({"dashboard_enabled": False, "preferences_saved": True,
                              "stop_requested": bool(info), "job_monitors_unaffected": True}, ensure_ascii=False, indent=2))
            return
        enabled = load_dashboard_enabled()
        host = args.host or ssh_target(load_config())
        if args.action == "serve":
            serve(host)
            return
        if args.action in ("start", "open"):
            result = start(host, open_window=args.action == "open" or args.open_if_new,
                           only_if_created=args.action == "start")
        else:
            info = current(host)
            if info is None:
                result = {"running": False}
            elif args.action == "status":
                result = {"running": True, **public_info(info), "jobs": len(jobs(host))}
            else:
                os.kill(info["pid"], signal.SIGTERM)
                result = {"stop_requested": True, "dashboard_pid": info["pid"],
                          "job_monitors_unaffected": True}
        result["dashboard_enabled"] = enabled
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
