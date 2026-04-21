"""One-shot Flux smoke test against the running ComfyUI container.

Submits ``comfyui_workflows/flux_still.json`` with a Vesper-style
horror prompt, polls /history for completion, downloads the PNG
to ``output/vesper/flux_smoke/``.

Not part of the pipeline — diagnostic only. Validates that:
  * The workflow JSON matches the installed node set.
  * Flux weights + CLIP + VAE are in the right dirs.
  * A Flux generation actually completes on the server 3090.

Run from the server:

    cd /opt/commoncreed/scripts
    /opt/commoncreed/.venv-vesper/bin/python3 -m vesper_pipeline.smoke_flux
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

_SCRIPTS = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SCRIPTS.parent

logger = logging.getLogger(__name__)


DEFAULT_PROMPT = (
    "cinematic horror photograph, empty roadside diner at 2:47 am, "
    "cold fluorescent light, wet asphalt outside, a silhouette at the "
    "counter perfectly still, 35mm film, oxidized blood and bone palette, "
    "near-black background, high detail, no text no watermark"
)
DEFAULT_NEGATIVE = (
    "text, watermark, logo, signature, caption, subtitle, "
    "oversaturated, cartoon, anime, low quality"
)


def _substitute(obj, params):
    if isinstance(obj, str):
        for k, v in params.items():
            obj = obj.replace("{{" + k + "}}", str(v))
        return obj
    if isinstance(obj, dict):
        return {k: _substitute(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(x, params) for x in obj]
    return obj


def _coerce_numeric(workflow):
    """ComfyUI expects int/float for numeric inputs. Post-substitution
    they're strings; re-cast fields that should be numeric."""
    int_fields = {"steps", "seed", "width", "height", "batch_size"}
    float_fields = {"cfg", "denoise"}
    for node_id, node in workflow.items():
        if node_id.startswith("_"):
            continue
        inputs = node.get("inputs", {})
        for k, v in inputs.items():
            if isinstance(v, str):
                if k in int_fields:
                    inputs[k] = int(float(v))
                elif k in float_fields:
                    inputs[k] = float(v)
    return workflow


def run_smoke(
    *,
    comfyui_url: str = "http://localhost:8188",
    prompt: str = DEFAULT_PROMPT,
    negative: str = DEFAULT_NEGATIVE,
    output_dir: Path | None = None,
    width: int = 768,
    height: int = 1344,
    steps: int = 4,             # schnell: 4 steps
    cfg: float = 1.0,           # schnell: CFG=1
    timeout_s: int = 300,
) -> Path:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    workflow_path = _REPO_ROOT / "comfyui_workflows" / "flux_still.json"
    if not workflow_path.exists():
        raise RuntimeError(f"workflow not found: {workflow_path}")
    workflow = json.loads(workflow_path.read_text())
    # Strip the _meta key — ComfyUI rejects top-level non-numeric ids.
    workflow = {k: v for k, v in workflow.items() if not k.startswith("_")}

    seed = int(time.time_ns() % (2 ** 31))
    params = {
        "prompt": prompt,
        # Flux schnell ignores negative, but keep the token for
        # workflow compatibility with flux-dev versions.
        "negative_prompt": negative,
        "width": width,
        "height": height,
        "num_inference_steps": steps,
        "guidance_scale": cfg,
        "seed": seed,
    }
    sub = _substitute(workflow, params)
    sub = _coerce_numeric(sub)

    output_dir = output_dir or (_REPO_ROOT / "output" / "vesper" / "flux_smoke")
    output_dir.mkdir(parents=True, exist_ok=True)
    dbg_path = output_dir / "_workflow_sent.json"
    dbg_path.write_text(json.dumps(sub, indent=2))
    logger.info("Workflow debug: %s", dbg_path)

    client_id = str(uuid.uuid4())
    logger.info(
        "Submitting Flux (w=%d h=%d steps=%d cfg=%.1f seed=%d) → %s",
        width, height, steps, cfg, seed, comfyui_url,
    )
    t0 = time.monotonic()
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{comfyui_url}/prompt", json={
            "prompt": sub,
            "client_id": client_id,
        })
        if r.status_code != 200:
            raise RuntimeError(
                f"ComfyUI /prompt {r.status_code}: {r.text[:500]}"
            )
        data = r.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"no prompt_id: {data}")
        logger.info("Submitted: prompt_id=%s", prompt_id)

    # Poll /history.
    output_filename = None
    with httpx.Client(timeout=30) as c:
        while True:
            time.sleep(2)
            r = c.get(f"{comfyui_url}/history/{prompt_id}")
            r.raise_for_status()
            hist = r.json()
            entry = hist.get(prompt_id)
            if entry:
                outputs = entry.get("outputs", {})
                for node_id, node_out in outputs.items():
                    images = node_out.get("images") or []
                    if images:
                        output_filename = images[0].get("filename")
                        subfolder = images[0].get("subfolder", "")
                        break
                if output_filename:
                    break
            if time.monotonic() - t0 > timeout_s:
                raise RuntimeError(f"timeout {timeout_s}s waiting for Flux")
        gen_ms = (time.monotonic() - t0) * 1000

        # Download the PNG.
        out_path = output_dir / f"flux_smoke_{seed}.png"
        params_q = {"filename": output_filename}
        if subfolder:
            params_q["subfolder"] = subfolder
        r = c.get(f"{comfyui_url}/view", params=params_q)
        r.raise_for_status()
        out_path.write_bytes(r.content)

    logger.info(
        "Flux smoke OK: %.0f ms → %s (%d bytes)",
        gen_ms, out_path, out_path.stat().st_size,
    )
    return out_path


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8188")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--height", type=int, default=1344)
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--cfg", type=float, default=1.0)
    args = p.parse_args(argv)
    try:
        run_smoke(
            comfyui_url=args.url,
            prompt=args.prompt,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg=args.cfg,
        )
    except Exception as exc:
        logger.exception("smoke failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
