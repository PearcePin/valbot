from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from .storage import ROOT, data_dir


def task_name(root: Path):
    return "ValorantLineBot-" + hashlib.sha256(str(root).encode()).hexdigest()[:10]


def cron_block(root: Path, python: Path, directory: Path):
    marker = task_name(root)
    command = shlex.join([str(python), str(root / "run_daily.py"), "--data-dir", str(directory)])
    # Percent signs are interpreted by cron even inside shell quotes.
    command = command.replace("%", "\\%")
    log = shlex.quote(str(directory / "cron.log")).replace("%", "\\%")
    return f"# BEGIN {marker}\n5 8 * * * {command} >> {log} 2>&1\n# END {marker}\n"


def merge_crontab(existing: str, root: Path, block: str):
    marker = task_name(root)
    lines, skipping = [], False
    for line in existing.splitlines():
        if line == f"# BEGIN {marker}":
            skipping = True
        elif line == f"# END {marker}":
            skipping = False
        elif not skipping:
            lines.append(line)
    if skipping:
        raise RuntimeError("現有 valbot crontab 標記不完整，請先手動修復以避免覆蓋其他任務。")
    prefix = "\n".join(lines).rstrip()
    return (prefix + "\n" if prefix else "") + block


def windows_xml(root: Path, python: Path, directory: Path, user_sid: str):
    ET.register_namespace("", "http://schemas.microsoft.com/windows/2004/02/mit/task")
    namespace = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
    task = ET.Element(namespace + "Task", version="1.2")

    def add(parent, name, value=None, **attrs):
        node = ET.SubElement(parent, namespace + name, attrs)
        node.text = value
        return node

    trigger = add(add(task, "Triggers"), "CalendarTrigger")
    tomorrow = datetime.now().replace(hour=8, minute=5, second=0, microsecond=0)
    if tomorrow <= datetime.now():
        tomorrow += timedelta(days=1)
    add(trigger, "StartBoundary", tomorrow.isoformat())
    add(trigger, "Enabled", "true")
    add(add(trigger, "ScheduleByDay"), "DaysInterval", "1")
    principal = add(add(task, "Principals"), "Principal", id="Author")
    add(principal, "UserId", user_sid)
    add(principal, "LogonType", "InteractiveToken")
    add(principal, "RunLevel", "LeastPrivilege")
    settings = add(task, "Settings")
    for name, value in [("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                        ("StopIfGoingOnBatteries", "false"), ("StartWhenAvailable", "true"),
                        ("Enabled", "true"), ("Hidden", "true"), ("ExecutionTimeLimit", "PT10M")]:
        add(settings, name, value)
    actions = add(task, "Actions", Context="Author")
    action = add(actions, "Exec")
    pythonw = python.with_name("pythonw.exe")
    add(action, "Command", str(pythonw))
    add(action, "Arguments", subprocess.list2cmdline([str(root / "run_daily.py"), "--data-dir", str(directory)]))
    add(action, "WorkingDirectory", str(root))
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def register_schedule():
    root, python, directory = ROOT.resolve(), Path(sys.executable).absolute(), data_dir()
    if os.name == "nt":
        import csv
        result = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader([result.strip()]))[1]
        xml = directory / "daily-task.xml"
        xml.write_bytes(windows_xml(root, python, directory, sid))
        subprocess.run(["schtasks", "/Create", "/TN", task_name(root), "/XML", str(xml), "/F"],
                       check=True, capture_output=True)
        return f"Windows 工作排程 {task_name(root)}（主機本地時間 08:05；使用者需保持登入）"
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode and "no crontab" not in result.stderr.lower():
        raise RuntimeError("無法讀取 crontab；請確認已安裝 cron 且此使用者有權使用。")
    merged = merge_crontab(result.stdout, root, cron_block(root, python, directory))
    subprocess.run(["crontab", "-"], input=merged, text=True, check=True, capture_output=True)
    return "Linux crontab（主機本地時間 08:05）"
