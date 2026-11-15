"""Container probes. Exit quietly without logging credentials or responses."""

import argparse
import os

import httpx

from startnummer.app.operations import worker_health


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("api", "worker"))
    args = parser.parse_args(argv)
    try:
        if args.service == "worker":
            port = int(os.environ.get("STARTNUMMER_WORKER_PORT", "8766"))
            health = worker_health(f"http://127.0.0.1:{port}", os.environ["STARTNUMMER_WORKER_SECRET"])
            healthy = health.reachable and health.state in {"idle", "busy"}
        else:
            response = httpx.get("http://127.0.0.1:8000/api/health/ready", timeout=3, trust_env=False)
            healthy = response.is_success and response.json().get("ready") is True
    except (KeyError, ValueError, httpx.HTTPError):
        healthy = False
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
