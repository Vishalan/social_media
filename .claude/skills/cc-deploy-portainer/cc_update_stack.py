#!/usr/bin/env python3
"""Update an existing CommonCreed stack on Portainer with a new compose payload
and the latest .env from the NAS, then restart Postiz to pick up env changes."""
from __future__ import annotations
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error

# Self-signed TLS on the new Ubuntu Portainer instance
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

PORTAINER = "https://192.168.29.237:9443"
ENDPOINT_ID = 3
SERVER_HOST = "192.168.29.237"
SERVER_USER = "vishalan"
SERVER_ENV_PATH = "/opt/commoncreed/.env"


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


def fetch_env_from_server() -> list[dict]:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"{SERVER_USER}@{SERVER_HOST}", f"cat {SERVER_ENV_PATH}"],
        capture_output=True, text=True, check=True,
    )
    env: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env.append({"name": k.strip(), "value": v.strip().strip('"').strip("'")})
    print(f"  parsed {len(env)} env vars from server .env (values not echoed)")
    return env


def find_stack_id(jwt: str, name: str) -> int | None:
    req = urllib.request.Request(f"{PORTAINER}/api/stacks", headers={"Authorization": f"Bearer {jwt}"})
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
        ss = json.load(r)
    for s in ss:
        if s["Name"] == name:
            return s["Id"]
    return None


def regen_prod_compose() -> str:
    src = open("deploy/portainer/docker-compose.yml").read()
    out = (
        src.replace("../../scripts", "/opt/commoncreed/scripts")
        .replace("../../assets", "/opt/commoncreed/assets")
        .replace("../../secrets", "/opt/commoncreed/secrets")
        .replace("../../sidecar", "/opt/commoncreed/sidecar")
        .replace("../../.env", "/opt/commoncreed/.env")
        .replace("./postiz-nginx.conf", "/opt/commoncreed/deploy/portainer/postiz-nginx.conf")
        .replace("./temporal-dynamicconfig", "/opt/commoncreed/deploy/portainer/temporal-dynamicconfig")
    )
    # Strip the sidecar's build: block (with optional comment lines between
    # build: and context:/dockerfile:). Portainer's sandboxed container can't
    # see the build context anyway — the image is pre-built on the host and
    # referenced by its `image:` tag instead.
    out = re.sub(
        r"  commoncreed_sidecar:\n    build:\n(?:      [^\n]*\n)+",
        "  commoncreed_sidecar:\n",
        out,
    )
    # Assert no UNCOMMENTED build: lines remain (commented Remotion service is OK).
    uncommented_build = [ln for ln in out.splitlines() if ln.lstrip().startswith("build:")]
    assert not uncommented_build, f"uncommented build: lines remain: {uncommented_build}"
    assert "image: commoncreed/sidecar:0.1.0" in out
    return out


def update_stack(jwt: str, stack_id: int, compose: str, env: list[dict]) -> dict:
    body = json.dumps({"stackFileContent": compose, "env": env, "prune": True}).encode()
    req = urllib.request.Request(
        f"{PORTAINER}/api/stacks/{stack_id}?endpointId={ENDPOINT_ID}",
        data=body, method="PUT",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=900, context=_SSL_CTX) as r:
        return json.loads(r.read())


def restart_container(jwt: str, name: str) -> bool:
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/json?filters=%7B%22name%22%3A%5B%22{name}%22%5D%7D",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
        cc = json.load(r)
    cid = next((c["Id"] for c in cc if c["Names"][0] == f"/{name}"), None)
    if not cid:
        print(f"  ✗ container {name} not found")
        return False
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/{cid}/restart?t=10",
        method="POST", headers={"Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as r:
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

    print("[4] fetch latest .env from server")
    env = fetch_env_from_server()

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
                f"http://{SERVER_HOST}:5000/api/auth/register",
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
