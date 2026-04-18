#!/usr/bin/env python3
"""Tail container logs from the CommonCreed stack via Portainer's REST API.

Works without SSH (useful when debugging the NAS from a different network).
Strips Docker's framed-stream multiplex bytes so output is human-readable.

Usage:
    cc_logs.py <service>           # last 200 lines
    cc_logs.py <service> --tail 50 # last 50 lines
    cc_logs.py <service> --follow  # stream in real time
    cc_logs.py --all               # last 50 from every service in the stack
    cc_logs.py --grep ERROR <svc>  # filter (basic substring match)

Service names (full container names):
    commoncreed_postgres
    commoncreed_redis
    commoncreed_temporal_postgres
    commoncreed_temporal_elasticsearch
    commoncreed_temporal
    commoncreed_postiz
    commoncreed_sidecar
"""
from __future__ import annotations
import argparse
import json
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error

PORTAINER = "https://192.168.29.237:9443"
ENDPOINT_ID = 3

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE
EXPECTED = [
    "commoncreed_postgres",
    "commoncreed_redis",
    "commoncreed_temporal_postgres",
    "commoncreed_temporal_elasticsearch",
    "commoncreed_temporal",
    "commoncreed_postiz",
    "commoncreed_sidecar",
]


def get_jwt() -> str:
    pw = subprocess.check_output(
        ["security", "find-generic-password", "-a", "vishalan", "-s", "commoncreed-portainer-new", "-w"],
        text=True,
    ).strip()
    req = urllib.request.Request(
        f"{PORTAINER}/api/auth",
        data=json.dumps({"username": "admin", "password": pw}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
        return json.loads(r.read())["jwt"]


def find_container_id(jwt: str, name: str) -> str | None:
    qs = urllib.parse.urlencode({"all": "true", "filters": json.dumps({"name": [name]})})
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/json?{qs}",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
        cc = json.load(r)
    for c in cc:
        if c["Names"][0] == f"/{name}":
            return c["Id"]
    return None


def strip_docker_frames(raw: bytes) -> str:
    """Docker logs API streams an 8-byte frame header before each chunk:
    [stream_id:1][reserved:3][length:4]. Strip them for plain reading."""
    out = bytearray()
    i = 0
    while i + 8 <= len(raw):
        # Frame header
        stream_id = raw[i]
        if stream_id not in (0, 1, 2):
            # Not a Docker frame — fallback to raw bytes
            return raw.decode("utf-8", "replace")
        length = int.from_bytes(raw[i + 4:i + 8], "big")
        i += 8
        out.extend(raw[i:i + length])
        i += length
    return out.decode("utf-8", "replace")


def fetch_logs(jwt: str, cid: str, tail: int = 200, follow: bool = False) -> str:
    qs = urllib.parse.urlencode(
        {"stdout": "true", "stderr": "true", "tail": str(tail), "timestamps": "true",
         "follow": "true" if follow else "false"}
    )
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/{cid}/logs?{qs}",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    if follow:
        # Stream and print line-buffered
        with urllib.request.urlopen(req, timeout=None, context=_SSL_CTX) as r:
            buf = bytearray()
            while True:
                chunk = r.read(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                text = strip_docker_frames(bytes(buf))
                if "\n" in text:
                    *complete, partial = text.rsplit("\n", 1)
                    for line in complete:
                        print(line)
                    sys.stdout.flush()
                    buf = bytearray(partial.encode("utf-8"))
        return ""
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as r:
        return strip_docker_frames(r.read())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("service", nargs="?", help="container name (e.g. commoncreed_postiz)")
    p.add_argument("--all", action="store_true", help="last N lines from all services")
    p.add_argument("--tail", type=int, default=200)
    p.add_argument("--follow", "-f", action="store_true")
    p.add_argument("--grep", help="filter lines by substring")
    args = p.parse_args()

    if not args.service and not args.all:
        p.error("specify a service name or --all")

    jwt = get_jwt()

    services = EXPECTED if args.all else [args.service]
    tail = 50 if args.all else args.tail

    for svc in services:
        cid = find_container_id(jwt, svc)
        if cid is None:
            print(f"[{svc}] ✗ not found")
            continue
        if args.all:
            print(f"\n=== {svc} (last {tail}) ===")
        out = fetch_logs(jwt, cid, tail=tail, follow=args.follow and not args.all)
        if args.grep:
            out = "\n".join(line for line in out.splitlines() if args.grep.lower() in line.lower())
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
