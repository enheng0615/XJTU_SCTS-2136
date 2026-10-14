#!/usr/bin/env python3
"""Per-user connection settings kept outside the distributable skill."""
import json
import os
import re
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("CLUSTER_SLURM_CONFIG", "~/.config/cluster-slurm/config.json")).expanduser()
PREFS_PATH = Path(os.environ.get("CLUSTER_SLURM_PREFERENCES", "~/.config/cluster-slurm/preferences.json")).expanduser()


def load_dashboard_enabled():
    """The dashboard is opt-out; preferences contain no SSH credentials."""
    if not PREFS_PATH.exists():
        return True
    try:
        preferences = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read dashboard preferences {PREFS_PATH}: {exc}") from exc
    enabled = preferences.get("dashboard_enabled")
    if type(enabled) is not bool:
        raise ValueError(f"dashboard_enabled in {PREFS_PATH} must be true or false")
    return enabled


def save_dashboard_enabled(enabled):
    if type(enabled) is not bool:
        raise TypeError("dashboard_enabled must be a boolean")
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(PREFS_PATH.parent, 0o700)
    temporary = PREFS_PATH.with_name(PREFS_PATH.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump({"dashboard_enabled": enabled}, stream, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        temporary.replace(PREFS_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    return PREFS_PATH


def validate(settings):
    for key in ("ssh_host", "ssh_user", "login_hostname"):
        value = settings.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError(f"配置项 {key} 必须是主机名、IP 或用户名，且不能留空")
    return {key: settings[key] for key in ("ssh_host", "ssh_user", "login_hostname")}


def load():
    if not CONFIG_PATH.is_file():
        raise RuntimeError(f"未找到本机集群配置 {CONFIG_PATH}；先运行 cluster.py configure --host HOST --ssh-user USER --login-hostname NAME")
    return validate(json.loads(CONFIG_PATH.read_text()))


def save(settings):
    clean = validate(settings)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CONFIG_PATH.parent, 0o700)
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG_PATH)
    finally:
        tmp.unlink(missing_ok=True)
    return CONFIG_PATH


def target(settings):
    clean = validate(settings)
    return clean["ssh_user"] + "@" + clean["ssh_host"]
