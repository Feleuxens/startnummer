"""Process identity and parent lifetime checks for Linux and macOS."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import psutil


def process_identity(pid):
    if not isinstance(pid, int) or pid <= 0:
        return None
    if sys.platform == "linux":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return None if stat[0] == "Z" else stat[19]
        except (OSError, IndexError):
            return None
    try:
        process = psutil.Process(pid)
        return None if process.status() == psutil.STATUS_ZOMBIE else str(process.create_time())
    except psutil.Error:
        return None


def start_parent_guard(lifetime):
    """Keep a separate watchdog alive while native code may hold the GIL."""
    pid = os.getpid()
    guardian = subprocess.Popen(
        [sys.executable, "-m", "startnummer.app.processes", str(pid), process_identity(pid)],
        stdin=lifetime,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    lifetime.close()
    ready = guardian.stdout.readline()
    guardian.stdout.close()
    if ready != b"ready\n":
        guardian.wait(timeout=5)
        raise RuntimeError("Could not start the inference parent-lifetime guard")
    # Do not wait for this helper on child exit: the queue worker closes its pipe
    # after joining inference. Popen helpers are not multiprocessing children.
    return guardian


def watch_parent(pid, identity):
    print("ready", flush=True)
    sys.stdin.buffer.read(1)
    if process_identity(pid) == identity:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    watch_parent(int(sys.argv[1]), sys.argv[2])
