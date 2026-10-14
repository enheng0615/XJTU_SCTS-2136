#!/usr/bin/env python3
"""Install the same skill and matching PreToolUse hook for Codex/Claude/Trae."""
import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HOME = Path.home()
DATA = HOME / ".local" / "share" / "cluster-slurm"
SKILL_BACKUPS = DATA.parent / "cluster-slurm-backups"
SKILL_IGNORE = shutil.ignore_patterns(".git", "install.py", "INSTALL.md", "README.md", "evals", "tests", "__pycache__", "*.pyc")
TARGETS = {
    "codex": (HOME / ".codex" / "skills" / "cluster-slurm", HOME / ".codex" / "hooks.json", "Bash"),
    "claude": (HOME / ".claude" / "skills" / "cluster-slurm", HOME / ".claude" / "settings.json", "Bash"),
    "trae": (HOME / ".trae-cn" / "skills" / "cluster-slurm", HOME / ".trae-cn" / "hooks.json", "RunCommand"),
}


def backup(path):
    if path.exists():
        dest = path.with_name(path.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        shutil.copy2(path, dest)
        return dest
    return None


def copy_skill(dest, platform):
    if dest.exists():
        if not dest.is_dir():
            raise RuntimeError(f"目标存在且不是目录: {dest}")
        SKILL_BACKUPS.mkdir(parents=True, exist_ok=True)
        archived = SKILL_BACKUPS / (platform + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        dest.rename(archived)
    shutil.copytree(ROOT, dest, ignore=SKILL_IGNORE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["codex", "claude", "trae", "all"], default="all")
    args = parser.parse_args()
    selected = TARGETS if args.platform == "all" else {args.platform: TARGETS[args.platform]}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    if DATA.exists():
        archived = DATA.with_name(DATA.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        DATA.rename(archived)
    shutil.copytree(ROOT, DATA, ignore=SKILL_IGNORE)
    command = "python3 " + str(DATA / "hooks" / "guard.py")
    for platform, (skill, config, matcher) in selected.items():
        skill.parent.mkdir(parents=True, exist_ok=True)
        copy_skill(skill, platform)
        config.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(config.read_text()) if config.exists() else {}
        if not isinstance(data, dict): raise RuntimeError(f"JSON 顶层必须是对象: {config}")
        if platform == "trae": data.setdefault("version", 1)
        hooks = data.setdefault("hooks", {})
        groups = hooks.setdefault("PreToolUse", [])
        groups[:] = [g for g in groups if not any("cluster-slurm/hooks/guard.py" in h.get("command", "") for h in g.get("hooks", []))]
        groups.append({"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 10}]})
        old = backup(config)
        config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(f"{platform}: skill={skill} hook={config}" + (f" backup={old}" if old else ""))


if __name__ == "__main__": main()
