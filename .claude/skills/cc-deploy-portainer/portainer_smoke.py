#!/usr/bin/env python3
"""Portainer API smoke test for cc-deploy-portainer skill."""
from __future__ import annotations
import json
import subprocess
import urllib.request
import urllib.error
from typing import Optional

PORTAINER_URL = "https://192.168.29.237:9443"
USERNAME = "admin"


def keychain_password() -> str:
    return subprocess.check_output(
        ["security", "find-generic-password", "-a", USERNAME, "-s", "commoncreed-portainer", "-w"],
        text=True,
    ).strip()


def http(method: str, path: str, jwt: Optional[str] = None, body: Optional[dict] = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{PORTAINER_URL}{path}", method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode("utf-8", "replace")[:300]}


def main() -> int:
    print("=" * 60)
    print("Portainer smoke test")
    print("=" * 60)

    print("\n[1/4] Auth")
    resp = http("POST", "/api/auth", body={"username": USERNAME, "password": keychain_password()})
    if "jwt" not in resp:
        print(f"  ✗ {resp}")
        return 1
    jwt = resp["jwt"]
    print(f"  ✓ JWT obtained ({len(jwt)} chars)")

    print("\n[2/4] List endpoints")
    endpoints = http("GET", "/api/endpoints", jwt=jwt)
    if not isinstance(endpoints, list):
        print(f"  ✗ {endpoints}")
        return 1
    docker_endpoints = [e for e in endpoints if e.get("Type") == 1]
    if not docker_endpoints:
        print("  ✗ no local Docker endpoints found")
        return 1
    ep = docker_endpoints[0]
    print(f"  ✓ id={ep['Id']}  name={ep['Name']}  status={ep.get('Status')}")
    endpoint_id = ep["Id"]

    print("\n[3/4] List existing stacks")
    stacks = http("GET", "/api/stacks", jwt=jwt)
    if not isinstance(stacks, list):
        print(f"  ✗ {stacks}")
        return 1
    if not stacks:
        print("  ✓ (0 stacks — fresh install)")
    else:
        for s in stacks:
            print(f"  - id={s['Id']}  name={s['Name']}  status={s.get('Status')}")

    print("\n[4/4] Sample container list (proves Docker socket reachable through Portainer)")
    containers = http("GET", f"/api/endpoints/{endpoint_id}/docker/containers/json?all=true", jwt=jwt)
    if not isinstance(containers, list):
        print(f"  ✗ {containers}")
        return 1
    print(f"  ✓ {len(containers)} containers visible")
    for c in containers[:5]:
        names = ",".join(c.get("Names", ["?"])).lstrip("/")
        print(f"  - {names}  state={c.get('State')}  image={c.get('Image')}")

    print("\n" + "=" * 60)
    print(f"✓ All checks passed. Endpoint ID for the deploy skill: {endpoint_id}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
