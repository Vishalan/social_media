#!/usr/bin/env python3
"""Update the CommonCreed Portainer stack.

Pipeline (each step fails fast with a clear prefix so log scrapers can pinpoint):

  [1]  Portainer auth (keychain → JWT)
  [2]  Resolve stack id
  [3]  Sync repo → /opt/commoncreed on the server (tar-over-ssh). Prevents the
       classic "server has stale code" drift where bind-mounted paths see
       yesterday's files and Portainer re-creates containers that read them.
  [4]  Regenerate prod compose (rewrite relative paths, strip build blocks)
       + validate with PyYAML so a malformed rewrite doesn't reach Portainer.
  [5]  Pre-flight: verify required images exist on the docker daemon
       (Portainer can't pull the :0.1.0 tags from anywhere — build locally first).
  [6]  Fetch latest .env from server (paths mount it, values parsed for Portainer env).
  [7]  PUT updated stack to Portainer.
  [8]  Kick containers that need env-refresh (Postiz — others use bind-mounts).
  [9]  Poll health endpoints on sidecar AND Postiz until both return.

Exit codes:
  0  everything passed
  2  step 3 (code sync) failed
  3  step 4 (compose rewrite/validate) failed
  4  step 5 (image pre-flight) failed
  5  step 7 (stack PUT) failed
  6  step 9 (post-deploy health) failed
"""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Self-signed TLS on the Ubuntu Portainer instance
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

PORTAINER = "https://192.168.29.237:9443"
ENDPOINT_ID = 3
SERVER_HOST = "192.168.29.237"
SERVER_USER = "vishalan"
SERVER_ENV_PATH = "/opt/commoncreed/.env"
SERVER_ROOT = "/opt/commoncreed"

# Resolve the repo root from this file's location so the script works no
# matter the caller's cwd. .claude/skills/cc-deploy-portainer/cc_update_stack.py
# is 3 levels below repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "deploy" / "portainer" / "docker-compose.yml"

# Images Portainer expects to be present on the docker daemon. Adding one
# here without a matching image on the server will surface at step 5 with a
# clear error instead of a cryptic Portainer "Pulling..." loop.
REQUIRED_IMAGES = [
    "commoncreed/sidecar:0.1.0",
    "commoncreed/remotion:0.1.0",
    "commoncreed/chatterbox:0.1.0",
]

# Post-deploy health endpoints. Each entry is (label, url, expected_status,
# method, body). Success = either the expected_status OR any 2xx/400 on paths
# where 400 proves the backend is up (Postiz /register returns 400 on empty body).
HEALTH_CHECKS = [
    (
        "sidecar",
        f"http://{SERVER_HOST}:5050/health",
        200,
        "GET",
        None,
    ),
    (
        "postiz",
        f"http://{SERVER_HOST}:5000/api/auth/register",
        400,
        "POST",
        b"{}",
    ),
]


def _step(n: int, title: str) -> None:
    print(f"[{n}] {title}")


def _ok(msg: str = "") -> None:
    print(f"  \u2713 {msg}" if msg else "  \u2713")


def _fail(msg: str) -> None:
    print(f"  \u2717 {msg}")


def get_jwt() -> str:
    pw = subprocess.check_output(
        ["security", "find-generic-password",
         "-a", "vishalan", "-s", "commoncreed-portainer-new", "-w"],
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


def find_stack_id(jwt: str, name: str) -> int | None:
    req = urllib.request.Request(
        f"{PORTAINER}/api/stacks", headers={"Authorization": f"Bearer {jwt}"}
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
        ss = json.load(r)
    for s in ss:
        if s["Name"] == name:
            return s["Id"]
    return None


def sync_repo_to_server() -> None:
    """tar-over-ssh from repo root → /opt/commoncreed, with hard excludes.

    Never sends .git, secrets, build artifacts, node_modules, or .env — so a
    missed exclude can't leak a credential file to the server. .env is
    deliberately NOT synced (the server owns it); the sidecar bind-mounts it.
    """
    excludes = [
        ".git", ".github", ".claude", ".worktrees",
        "__pycache__", "*.pyc",
        "node_modules",
        "output", ".venv", "venv",
        ".env", ".env.*", "secrets",
        ".DS_Store", "._*",
        "docs/plans", "docs/brainstorms", "docs/solutions",
    ]
    tar_args = ["tar"]
    for e in excludes:
        tar_args += ["--exclude", e]
    tar_args += ["-cf", "-", "."]

    # macOS tar emits AppleDouble headers unless disabled.
    env = os.environ.copy()
    env["COPYFILE_DISABLE"] = "1"

    with subprocess.Popen(
        tar_args, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, env=env,
    ) as tar_proc:
        ssh_proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", f"{SERVER_USER}@{SERVER_HOST}",
             f"cd {SERVER_ROOT} && tar -xf -"],
            stdin=tar_proc.stdout, capture_output=True, text=True,
        )
        tar_proc.stdout.close()
        tar_rc = tar_proc.wait()
    if tar_rc != 0:
        raise RuntimeError(f"local tar failed (rc={tar_rc})")
    if ssh_proc.returncode != 0:
        raise RuntimeError(
            f"remote tar -xf failed (rc={ssh_proc.returncode}): "
            f"{ssh_proc.stderr[-500:]}"
        )


def regen_prod_compose() -> str:
    """Rewrite relative paths to absolute server paths + strip build blocks.

    Validates the result is parseable YAML before returning. A malformed
    compose was previously only caught by Portainer returning HTTP 400 with
    a terse message — now we catch it locally with the exact YAML error line.
    """
    src = COMPOSE_PATH.read_text()
    out = (
        src.replace("../../scripts", f"{SERVER_ROOT}/scripts")
        .replace("../../assets", f"{SERVER_ROOT}/assets")
        .replace("../../secrets", f"{SERVER_ROOT}/secrets")
        .replace("../../sidecar", f"{SERVER_ROOT}/sidecar")
        .replace("../../.env", f"{SERVER_ROOT}/.env")
        .replace("./postiz-nginx.conf", f"{SERVER_ROOT}/deploy/portainer/postiz-nginx.conf")
        .replace("./temporal-dynamicconfig", f"{SERVER_ROOT}/deploy/portainer/temporal-dynamicconfig")
    )
    # Strip ALL service build: blocks. Portainer's sandboxed container can't
    # see build contexts on the host; buildable services must already exist
    # as pre-built images on the docker daemon (we verify in step 5).
    out = re.sub(
        r"^(  \w+:)\n    build:\n(?:      [^\n]*\n)+",
        r"\1\n",
        out,
        flags=re.MULTILINE,
    )
    # Fail on UNCOMMENTED build: lines (commented references fine).
    stragglers = [ln for ln in out.splitlines()
                  if ln.lstrip().startswith("build:")]
    if stragglers:
        raise RuntimeError(
            f"regen left {len(stragglers)} uncommented build: lines — regex missed them: "
            f"{stragglers[:3]}"
        )

    # Validate it's still parseable YAML. Prevents a malformed rewrite from
    # reaching Portainer only to fail with HTTP 400.
    try:
        import yaml  # noqa: WPS433 — deferred import, yaml is a dev-only dep
        parsed = yaml.safe_load(out)
    except ImportError:
        # PyYAML not available locally — fall back to a structural sanity check.
        if "services:" not in out or "image:" not in out:
            raise RuntimeError("compose rewrite lost services: or image: blocks")
    except yaml.YAMLError as exc:
        raise RuntimeError(f"compose rewrite produced invalid YAML: {exc}") from exc
    else:
        if not parsed or "services" not in parsed:
            raise RuntimeError("compose rewrite has no services: key")
        missing_image_refs: list[str] = []
        for name, svc in parsed["services"].items():
            if "image" not in svc:
                missing_image_refs.append(name)
        if missing_image_refs:
            raise RuntimeError(
                f"services without image: keys after build-block strip: "
                f"{missing_image_refs}"
            )
    return out


def check_server_images_present() -> list[str]:
    """Return the list of REQUIRED_IMAGES missing from the server's docker daemon.

    Portainer picks images locally; if a required tag isn't there, the stack
    will fail to start and the sidecar will spend minutes "Pulling..." from
    docker.io (where our private images don't exist) before timing out.
    Catching this locally saves that debug loop.
    """
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"{SERVER_USER}@{SERVER_HOST}",
         "docker image ls --format '{{.Repository}}:{{.Tag}}'"],
        capture_output=True, text=True, check=True,
    )
    present = set(result.stdout.splitlines())
    return [img for img in REQUIRED_IMAGES if img not in present]


def fetch_env_from_server() -> list[dict]:
    """Parse /opt/commoncreed/.env to the list-of-dicts shape Portainer wants.

    Values are NEVER echoed. The count is the only thing printed — debug hooks
    that dump the list are a foot-gun for a public transcript.
    """
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"{SERVER_USER}@{SERVER_HOST}",
         f"cat {SERVER_ENV_PATH}"],
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


def update_stack(jwt: str, stack_id: int, compose: str, env: list[dict]) -> dict:
    body = json.dumps(
        {"stackFileContent": compose, "env": env, "prune": True}
    ).encode()
    req = urllib.request.Request(
        f"{PORTAINER}/api/stacks/{stack_id}?endpointId={ENDPOINT_ID}",
        data=body, method="PUT",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=900, context=_SSL_CTX) as r:
        return json.loads(r.read())


def restart_container(jwt: str, name: str) -> bool:
    filters = f'%7B%22name%22%3A%5B%22{name}%22%5D%7D'
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/json?filters={filters}",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as r:
        cc = json.load(r)
    cid = next((c["Id"] for c in cc if c["Names"][0] == f"/{name}"), None)
    if not cid:
        _fail(f"container {name} not found")
        return False
    req = urllib.request.Request(
        f"{PORTAINER}/api/endpoints/{ENDPOINT_ID}/docker/containers/{cid}/restart?t=10",
        method="POST", headers={"Authorization": f"Bearer {jwt}"},
    )
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as r:
        r.read()
    _ok(f"{name} restart issued")
    return True


def _poll_one(label: str, url: str, expected: int, method: str, body: bytes | None) -> bool:
    for i in range(1, 11):
        time.sleep(15)
        code = 0
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"} if body is not None else {},
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
        except Exception:
            code = 0
        print(f"  {label} t+{i*15}s: HTTP {code}")
        if code == expected:
            _ok(f"{label} ready")
            return True
    _fail(f"{label} never came back — check `docker logs commoncreed_{label}`")
    return False


def main() -> int:
    _step(1, "Portainer auth (keychain → JWT)")
    try:
        jwt = get_jwt()
        _ok()
    except Exception as exc:
        _fail(f"auth failed: {exc}")
        return 5

    _step(2, "resolve stack id")
    sid = find_stack_id(jwt, "commoncreed")
    if sid is None:
        _fail("no 'commoncreed' stack — run cc-deploy-portainer for fresh deploy")
        return 5
    _ok(f"stack id={sid}")

    _step(3, f"sync repo → {SERVER_HOST}:{SERVER_ROOT} (tar-over-ssh)")
    t0 = time.time()
    try:
        sync_repo_to_server()
        _ok(f"synced in {time.time()-t0:.0f}s")
    except Exception as exc:
        _fail(f"sync failed: {exc}")
        return 2

    _step(4, "regenerate + validate prod compose")
    try:
        compose = regen_prod_compose()
        _ok(f"{len(compose)} bytes, YAML-valid")
    except Exception as exc:
        _fail(f"compose rewrite failed: {exc}")
        return 3

    _step(5, "pre-flight: required images present on server")
    try:
        missing = check_server_images_present()
    except Exception as exc:
        _fail(f"image check failed: {exc}")
        return 4
    if missing:
        _fail(f"missing images on server: {missing}")
        print("  Hint: build them first, e.g.")
        print(f"    ssh {SERVER_USER}@{SERVER_HOST} 'cd {SERVER_ROOT} && "
              "docker build -t commoncreed/sidecar:0.1.0 -f sidecar/Dockerfile .'")
        return 4
    _ok(f"all {len(REQUIRED_IMAGES)} required images present")

    _step(6, "fetch latest .env from server")
    env = fetch_env_from_server()

    _step(7, "PUT updated stack to Portainer")
    t0 = time.time()
    try:
        update_stack(jwt, sid, compose, env)
        _ok(f"updated in {time.time()-t0:.0f}s")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        _fail(f"HTTP {e.code} after {time.time()-t0:.0f}s")
        print(body[:1500])
        return 5

    _step(8, "kick env-consumers (Postiz)")
    restart_container(jwt, "commoncreed_postiz")

    _step(9, "post-deploy health polls")
    all_ok = True
    for label, url, expected, method, body in HEALTH_CHECKS:
        if not _poll_one(label, url, expected, method, body):
            all_ok = False
    if not all_ok:
        return 6

    print()
    print("\u2713 deploy complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
