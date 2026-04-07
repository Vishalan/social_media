#!/usr/bin/env python3
"""Update an existing CommonCreed stack on Portainer with a new compose payload
and the latest .env from the NAS, then restart Postiz to pick up env changes."""
from __future__ import annotations
import json
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

PORTAINER = "http://192.168.29.211:9000"
ENDPOINT_ID = 3
NAS_HOST = "192.168.29.211"
NAS_USER = "vishalan"
NAS_ENV_PATH = "/volume1/docker/commoncreed/.env"


def get_jwt() -> str:
    pw = subprocess.check_output(
        ["security", "find-generic-password", "-a", "vishalan", "-s", "commoncreed-portainer", "-w"],
        text=True,
    ).strip()
    req = urllib.request.Request(
        f"{PORTAINER}/api/auth",
        data=json.dumps({"username": "vishalan", "password": pw}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["jwt"]


def fetch_env_from_nas() -> list[dict]:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"{NAS_USER}@{NAS_HOST}", f"cat {NAS_ENV_PATH}"],
        capture_output=True, text=True, check=True,
    )
    env: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env.append({"name": k.strip(), "value": v.strip().strip('"').strip("'")})
    print(f"  parsed {len(env)} env vars from NAS .env (values not echoed)")
    return env


def find_stack_id(jwt: str, name: str) -> int | None:
    req = urllib.request.Request(f"{PORTAINER}/api/stacks", headers={"Authorization": f"Bearer {jwt}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        ss = json.load(r)
    for s in ss:
        if s["Name"] == name:
            return s["Id"]
    return None


def regen_prod_compose() -> str:
    src = open("deploy/portainer/docker-compose.yml").read()
    out = (
        src.replace("../../scripts", "/volume1/docker/commoncreed/scripts")
        .replace("../../assets", "/volume1/docker/commoncreed/assets")
        .replace("../../sidecar", "/volume1/docker/commoncreed/sidecar")
        .replace("../../.env", "/volume1/docker/commoncreed/.env")
        .replace("./postiz-nginx.conf", "/volume1/docker/commoncreed/deploy/portainer/postiz-nginx.conf")
        .replace("./temporal-dynamicconfig", "/volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig")
    )
    out = re.sub(
        r"  commoncreed_sidecar:\n    build:\n      context: [^\n]+\n      dockerfile: [^\n]+\n",
        "  commoncreed_sidecar:\n",
        out,
    )
    assert "build:" not in out
    assert "image: commoncreed/sidecar:0.1.0" in out
    return out


def update_stack(jwt: str, stack_id: int, compose: str, env: list[dict]) -> dict:
    body = json.dumps({"stackFileContent": compose, "env": env, "prune": True}).encode()
    req = urllib.request.Request(
        f"{PORTAINER}/api/stacks/{stack_id}?endpointId={ENDPOINT_ID}",
        data=body, method="PUT",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def restart_container(jwt: str, name: str) -> bool:
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/json?filters=%7B%22name%22%3A%5B%22{name}%22%5D%7D",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        cc = json.load(r)
    cid = next((c["Id"] for c in cc if c["Names"][0] == f"/{name}"), None)
    if not cid:
        print(f"  ✗ container {name} not found")
        return False
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/{cid}/restart?t=10",
        method="POST", headers={"Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    print(f"  ✓ {name} restart issued")
    return True


def main() -> int:
    print("[1] auth")
    jwt = get_jwt()
    print("  ✓")

    print("[2] find existing stack")
    sid = find_stack_id(jwt, "commoncreed")
    if sid is None:
        print("  ✗ no commoncreed stack — run cc-deploy-portainer first for fresh deploy")
        return 1
    print(f"  ✓ stack id={sid}")

    print("[3] regenerate prod compose payload")
    compose = regen_prod_compose()
    print(f"  ✓ {len(compose)} bytes")

    print("[4] fetch latest .env from NAS")
    env = fetch_env_from_nas()

    print("[5] PUT updated stack to Portainer")
    t0 = time.time()
    try:
        result = update_stack(jwt, sid, compose, env)
        print(f"  ✓ updated in {time.time()-t0:.0f}s")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"  ✗ HTTP {e.code} after {time.time()-t0:.0f}s")
        print(body[:1500])
        return 1

    print("[6] restart Postiz so it picks up new env vars")
    restart_container(jwt, "commoncreed_postiz")

    print("[7] poll backend until 400 (validation error = backend up)")
    for i in range(1, 11):
        time.sleep(15)
        try:
            req = urllib.request.Request(
                "http://192.168.29.211:5100/api/auth/register",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
        except Exception:
            code = 0
        print(f"  t+{i*15}s: HTTP {code}")
        if code == 400:
            print("  ✓ backend ready")
            return 0
    print("  ✗ backend never came back up — check logs")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
