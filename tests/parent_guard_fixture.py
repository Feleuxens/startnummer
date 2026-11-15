"""Synthetic inference process using the portable parent-lifetime watchdog."""

import json
import multiprocessing
import os
import time

from startnummer.app.processes import start_parent_guard


def child(lifetime, ready):
    guardian = start_parent_guard(lifetime)
    ready.send({"inference_pid": os.getpid(), "guardian_pid": guardian.pid})
    ready.close()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    context = multiprocessing.get_context("spawn")
    lifetime, writer = context.Pipe(duplex=False)
    reader, ready = context.Pipe(duplex=False)
    inference = context.Process(target=child, args=(lifetime, ready))
    inference.start()
    lifetime.close()
    ready.close()
    print(json.dumps(reader.recv()), flush=True)
    while True:
        time.sleep(1)
