#!/usr/bin/env python3
"""PreToolUse guard for direct AI SSH sessions to the CPU login node."""
import json
import os
import re
import sys
from pathlib import Path


def target_names():
    names = set()
    settings_path = Path(os.environ.get("CLUSTER_SLURM_CONFIG", "~/.config/cluster-slurm/config.json")).expanduser()
    if settings_path.is_file():
        try:
            host = json.loads(settings_path.read_text()).get("ssh_host")
            if isinstance(host, str) and host:
                names.add(host)
        except (OSError, ValueError):
            pass
    names.update(x.strip() for x in os.environ.get("CLUSTER_SSH_HOSTS", "").split(",") if x.strip())
    config = Path.home() / ".ssh" / "config"
    if config.exists():
        aliases = []
        mappings = {}
        try:
            for raw in config.read_text().splitlines():
                line = raw.split("#", 1)[0].strip()
                parts = line.split()
                if not parts: continue
                if parts[0].lower() == "host":
                    aliases = [x for x in parts[1:] if not any(c in x for c in "*?!")]
                elif parts[0].lower() == "hostname" and len(parts) > 1:
                    for alias in aliases:
                        mappings[alias] = parts[1]
            if any(alias in names for alias in mappings):
                names.update(value for alias, value in mappings.items() if alias in names)
            names.update(alias for alias, value in mappings.items() if value in names)
        except OSError:
            pass
    return names


def should_block(command):
    # Hook receives shell text, not a parsed AST. Deliberately prefer false
    # positives around this one cluster over letting obvious direct SSH pass.
    if not re.search(r"(?:^|[^\w.-])ssh(?:\s|$)", command):
        return False
    return any(re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(name) + r"(?![A-Za-z0-9_.-])", command) for name in target_names())


def main():
    try:
        event = json.load(sys.stdin)
        command = event.get("tool_input", {}).get("command") or event.get("tool_input", {}).get("cmd") or ""
        if should_block(command):
            json.dump({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "禁止 AI 直接 SSH 到配置的登录节点执行命令。请加载 cluster-slurm skill，使用 scripts/cluster.py inspect/plan/submit；计算只能通过 Slurm 在计算节点运行。"
            }}, sys.stdout, ensure_ascii=False)
    except Exception as exc:
        # A broken hook must be conspicuous. Codex/Claude/Trae may not fail
        # closed on hook errors, so deployment still needs server-side policy.
        print(f"cluster-slurm hook error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__": main()
