"""
Scheduler Execution - the scheduler agent's tool (Boundary V4)
=============================================================

The scheduler agent keeps no timer of its own. To set a wake-up it sends one
Python script through the bridge, which runs on the user's computer and:

  1. writes ~/Boundary/config.json: the server URL, the bridge identity token,
     the bridge's own Python, and the path of bridge.py when it can find it;
  2. writes the shared wake runner, ~/Boundary/wake/boundary_wake.py;
  3. writes one record per wake-up, ~/Boundary/wake/W-xxxxxxxx.json, holding
     the agent to wake and the message it left itself;
  4. registers a one-shot task in Windows Task Scheduler's \\Boundary\\ folder.

At the chosen time Windows runs the runner, not the bridge. The runner starts
the bridge if its window was closed, calls POST /api/bridge/wake, then removes
its own task and record. StartWhenAvailable fires a missed wake-up as soon as
the machine is back on; WakeToRun wakes a sleeping machine.

Every value travels inside one base64 block, so nothing an LLM writes can
become code. Standard library only, here and on the user's computer.
"""

import base64
import json
from typing import Any, Dict

RESULT_MARKER = "BOUNDARY_RESULT:"


# ─────────────────────────────────────────────────────────────────────────
# The wake runner, written to ~/Boundary/wake/boundary_wake.py
# ─────────────────────────────────────────────────────────────────────────
WAKE_RUNNER_SOURCE = r'''"""Boundary wake runner (written by Boundary's scheduler agent).

Windows Task Scheduler starts this file with a wake-up ID at the time an
agent chose. It starts the bridge if it is closed, asks Boundary's server to
wake the agent with the message it left itself, then removes its own task
and record. Safe to delete: the scheduler writes it again when needed.
"""
import base64
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path.home() / "Boundary"
WAKE = ROOT / "wake"
NO_WINDOW = 0x08000000
NEW_CONSOLE = 0x00000010


def log(line):
    try:
        with open(WAKE / "wake.log", "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  " + line + "\n")
    except Exception:
        pass


def powershell(script):
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)


def bridge_running(bridge_path):
    name = os.path.basename(bridge_path).replace("'", "''")
    r = powershell("@(Get-CimInstance Win32_Process -Filter \"Name LIKE 'py%'\" | "
                   "Where-Object { $_.CommandLine -like '*" + name + "*' }).Count")
    try:
        return int((r.stdout or "0").strip() or "0") > 0
    except ValueError:
        return True


def start_bridge(cfg):
    path = cfg.get("bridge_path") or ""
    python = cfg.get("python") or sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-len("pythonw.exe")] + "python.exe"
    if not path or not os.path.isfile(path):
        log("the bridge is not running and its path is unknown; the agent may wake without hands")
        return
    subprocess.Popen([python, path], cwd=os.path.dirname(path), creationflags=NEW_CONSOLE)
    log("started the bridge: " + path)
    time.sleep(10)


def main():
    if len(sys.argv) < 2:
        return
    wid = sys.argv[1]
    rec_path = WAKE / (wid + ".json")
    if not rec_path.exists():
        log(wid + " has no record (cancelled?); nothing to do")
        return
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    try:
        due = datetime.datetime.strptime(rec["run_at_local"], "%Y-%m-%d %H:%M:%S")
        late = max(0, int((datetime.datetime.now() - due).total_seconds() // 60))
    except Exception:
        late = 0

    if cfg.get("bridge_path") and not bridge_running(cfg["bridge_path"]):
        start_bridge(cfg)

    body = json.dumps({
        "wakeup_id": wid,
        "agent_id": rec.get("agent_id", ""),
        "message": rec.get("message", ""),
        "directive_id": rec.get("directive_id", ""),
        "kind": rec.get("kind", ""),
        "scheduled_for": rec.get("run_at_local", ""),
        "late_minutes": late,
    }).encode("utf-8")

    ok = False
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                cfg["api_base"].rstrip("/") + "/api/bridge/wake", data=body, method="POST",
                headers={"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                ok = 200 <= resp.status < 300
                log("%s woke agent %s (HTTP %s, %d min late)" % (wid, rec.get("agent_id", "?"), resp.status, late))
                break
        except Exception as e:
            log("%s attempt %d failed: %s" % (wid, attempt, e))
            time.sleep(30)

    if ok:
        powershell("Unregister-ScheduledTask -TaskPath '\\Boundary\\' -TaskName '" + wid +
                   "' -Confirm:$false -ErrorAction SilentlyContinue")
        try:
            rec_path.unlink()
        except Exception:
            pass
    else:
        rec["failed_local"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("runner error: %s: %s" % (type(e).__name__, e))
'''


# ─────────────────────────────────────────────────────────────────────────
# The script sent through the bridge (schedule / cancel / list)
# ─────────────────────────────────────────────────────────────────────────
_SCRIPT = r'''
import base64, datetime, json, os, re, subprocess, sys, uuid
from pathlib import Path

P = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
ROOT = Path.home() / "Boundary"
WAKE = ROOT / "wake"
NO_WINDOW = 0x08000000
FMT = "%Y-%m-%d %H:%M:%S"


def out(result):
    print("BOUNDARY_RESULT:" + json.dumps(result))


def ps(script, timeout=25):
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def q(text):
    return str(text).replace("'", "''")


def find_bridge_path():
    """This script is a child of the bridge process, so its parent's command line names bridge.py."""
    try:
        _, cmd, _ = ps("(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % os.getppid())
        for m in re.finditer(r'"([^"]+?\.py)"|(\S+?\.py)\b', cmd):
            path = m.group(1) or m.group(2)
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            if os.path.isfile(path):
                return os.path.abspath(path)
    except Exception:
        pass
    return ""


def load_config():
    try:
        return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_time(now):
    if P.get("delay_minutes") not in (None, ""):
        return now + datetime.timedelta(minutes=float(P["delay_minutes"]))
    if P.get("run_at"):
        dt = datetime.datetime.fromisoformat(str(P["run_at"]).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    if P.get("local_time"):
        hh, mm = [int(x) for x in str(P["local_time"]).split(":")[:2]]
        if P.get("local_date"):
            day = datetime.date.fromisoformat(str(P["local_date"])[:10])
        else:
            day = now.date() + datetime.timedelta(days=int(P.get("day_offset") or 0))
        return datetime.datetime.combine(day, datetime.time(hh, mm))
    if P.get("local_date"):
        return datetime.datetime.combine(datetime.date.fromisoformat(str(P["local_date"])[:10]), datetime.time(9, 0))
    raise ValueError("No time given: use delay_minutes, run_at, or local_time with day_offset or local_date")


def schedule():
    now = datetime.datetime.now().replace(microsecond=0)
    when = resolve_time(now).replace(microsecond=0)
    note = ""
    if when < now + datetime.timedelta(seconds=30):
        note = "The requested time had already passed, so the wake-up was set for one minute from now."
        when = now + datetime.timedelta(minutes=1)

    WAKE.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg.update({"api_key": P["api_key"], "api_base": P["api_base"], "python": sys.executable})
    bridge_path = find_bridge_path()
    if bridge_path:
        cfg["bridge_path"] = bridge_path
    (ROOT / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    runner = WAKE / "boundary_wake.py"
    runner.write_text(P["runner_source"], encoding="utf-8")

    wid = "W-" + uuid.uuid4().hex[:8]
    record = {
        "wakeup_id": wid,
        "agent_id": P["agent_id"],
        "message": P["message"],
        "directive_id": P.get("directive_id") or "",
        "kind": P.get("kind") or "",
        "run_at_local": when.strftime(FMT),
        "created_local": now.strftime(FMT),
    }
    rec_path = WAKE / (wid + ".json")
    rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable

    script = (
        "$a = New-ScheduledTaskAction -Execute '%s' -Argument '\"%s\" %s' -WorkingDirectory '%s'\n"
        "$t = New-ScheduledTaskTrigger -Once -At ([datetime]::ParseExact('%s', 'yyyy-MM-dd HH:mm:ss', "
        "[Globalization.CultureInfo]::InvariantCulture))\n"
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries\n"
        "Register-ScheduledTask -TaskPath '\\Boundary\\' -TaskName '%s' -Action $a -Trigger $t "
        "-Settings $s -Force | Out-Null\n"
        "'REGISTERED'"
    ) % (q(pythonw), q(str(runner)), wid, q(str(WAKE)), when.strftime(FMT), wid)

    _, stdout, stderr = ps(script)
    if "REGISTERED" not in stdout:
        try:
            rec_path.unlink()
        except Exception:
            pass
        out({"ok": False, "error": "Task Scheduler refused the wake-up: " + (stderr or stdout)[-400:]})
        return

    out({"ok": True, "action": "schedule", "wakeup_id": wid, "run_at_local": record["run_at_local"],
         "now_local": now.strftime(FMT), "agent_id": P["agent_id"], "directive_id": record["directive_id"],
         "kind": record["kind"], "message": P["message"], "bridge_path_known": bool(cfg.get("bridge_path")),
         "note": note})


def cancel():
    wid = str(P.get("wakeup_id") or "")
    if not re.fullmatch(r"W-[0-9a-f]{8}", wid):
        out({"ok": False, "error": "wakeup_id must look like W-1a2b3c4d"})
        return
    ps("Unregister-ScheduledTask -TaskPath '\\Boundary\\' -TaskName '%s' -Confirm:$false "
       "-ErrorAction SilentlyContinue; 'DONE'" % wid)
    rec = WAKE / (wid + ".json")
    existed = rec.exists()
    try:
        rec.unlink()
    except Exception:
        pass
    out({"ok": True, "action": "cancel", "wakeup_id": wid, "record_existed": existed})


def list_wakeups():
    tasks = {}
    _, stdout, _ = ps("Get-ScheduledTask -TaskPath '\\Boundary\\' -ErrorAction SilentlyContinue | "
                      "ForEach-Object { $i = Get-ScheduledTaskInfo $_; "
                      "$_.TaskName + '|' + $_.State + '|' + $i.NextRunTime }")
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            tasks[parts[0].strip()] = {"state": parts[1].strip(), "next_run": parts[2].strip()}
    items = []
    if WAKE.exists():
        for f in sorted(WAKE.glob("W-*.json")):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            t = tasks.get(rec.get("wakeup_id"), {})
            rec["task_state"] = t.get("state", "missing")
            rec["next_run"] = t.get("next_run", "")
            items.append(rec)
    out({"ok": True, "action": "list", "wakeups": items,
         "now_local": datetime.datetime.now().strftime(FMT)})


ACTIONS = {"schedule": schedule, "cancel": cancel, "list": list_wakeups}
try:
    action = ACTIONS.get(P.get("action"))
    if action is None:
        out({"ok": False, "error": "Unknown action: use schedule, cancel or list"})
    else:
        action()
except Exception as e:
    out({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
'''


def build_scheduler_code(action: str, params: Dict[str, Any]) -> str:
    """Python code for BridgeQuery.execute_python. All values ride in one base64 block."""
    payload = dict(params or {})
    payload["action"] = action
    if action == "schedule":
        payload["runner_source"] = WAKE_RUNNER_SOURCE
    blob = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return _SCRIPT.replace("__PAYLOAD__", blob)


def parse_result(output: str) -> Dict[str, Any]:
    """The script's last BOUNDARY_RESULT line, as a dict."""
    for line in reversed((output or "").splitlines()):
        line = line.strip()
        if line.startswith(RESULT_MARKER):
            try:
                return json.loads(line[len(RESULT_MARKER):])
            except json.JSONDecodeError:
                break
    return {"ok": False, "error": "The scheduler script returned no result", "raw": (output or "")[-500:]}