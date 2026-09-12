"""Generate the cover photograph: the owner's face, an imagined scene.

The reference grid is not composited — it is photographed, or generated to
look photographed. The person is in a real room holding a real object, lit by
a real lamp, and every frame is a different room. Cutting a talking-head frame
out of its background and standing it on a gradient cannot reach that, and the
attempt is visible: the ground has no objects in it and the subject is not
holding anything.

So the picture is generated and only the FACE is held fixed.

FLUX.1-dev with PuLID rather than InstantID, and the reason matters. InstantID
conditions on facial KEYPOINTS as well as identity, so the output inherits the
reference's head tilt and expression — feed it a frame of someone talking to
camera and every cover comes back as someone talking to camera. PuLID
conditions on identity alone, which is what allows the same face to appear
standing at a desk, sitting on a bed, or holding a printed sheet. The grid
does all three.

Text is still composited afterwards. Diffusion models remain unreliable at
display type, and the typography here is already measured and contrast-checked.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

COMFY = "http://127.0.0.1:8188"
COMFY_ROOT = "/home/vishalan/ComfyUI"

# Q4 first, Q8 only as a fallback.
#
# Q8 is 12GB, and layered on a warm ComfyUI holding T5, PuLID, EVA-CLIP and
# insightface it took this machine off the network twice — hard enough that
# no OOM trace survived in dmesg. The one run that succeeded had a cold card.
# Q4 gives back about six gigabytes for a difference invisible at the size a
# cover is viewed, and a cover that renders beats one that is sharper in
# principle.
UNET_CANDIDATES = ("flux1-dev-Q4_K_S.gguf", "flux1-dev-Q4_K_M.gguf",
                   "flux1-dev-Q8_0.gguf")
UNET = UNET_CANDIDATES[0]
CLIP_L = "clip_l.safetensors"
T5 = "t5xxl_fp8_e4m3fn.safetensors"
VAE = "flux-ae.safetensors"
PULID = "pulid_flux_v0.9.1.safetensors"

# The channel's look, appended to every scene brief so a grid of covers shares
# a world. Measured off the reference: warm practical lighting, shallow depth,
# a real room with things in it. These are the constants; the brief supplies
# the variable.
STYLE = (
    "photorealistic editorial portrait photograph, 85mm lens, shallow depth of "
    "field, warm tungsten practical lighting from a lamp just out of frame, "
    "soft golden falloff, lived-in room with books plants and warm wood, "
    "muted warm colour grade, natural skin texture, calm confident expression, "
    "looking at camera, shot on a full-frame camera, high detail"
)
# What the identity embedding does NOT carry.
#
# ArcFace is trained to be invariant to precisely the things that let you
# recognise someone across a room, because a recognition model has to match
# the same person with and without them. Glasses are the clearest case: he
# wears them in every available reference and the first generated cover had
# none, which is most of why it read as "a similar man" rather than "him".
#
# PuLID will never supply these. They have to be said in words, so they are.
TRAITS = ("wearing thin round metal-framed glasses, short dark hair, "
          "moustache and light stubble")
NEGATIVE = (
    "cartoon, illustration, 3d render, cgi, plastic skin, oversaturated, "
    "harsh flash, studio seamless backdrop, watermark, text, logo, letters, "
    "extra fingers, deformed hands, blurry face, duplicate person"
)


class PortraitError(RuntimeError):
    """Raised when a cover photograph cannot be generated."""


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{COMFY}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read() or b"{}")


def _duration(path: str) -> float:
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _resolve_unet() -> Optional[str]:
    """The smallest FLUX quantisation actually installed."""
    for name in UNET_CANDIDATES:
        p = Path(f"{COMFY_ROOT}/models/unet") / name
        if p.is_file() and p.stat().st_size > 1_000_000_000:
            return name
    return None


def available() -> bool:
    """Every weight present, or nothing is attempted."""
    unet = _resolve_unet()
    if not unet:
        logger.info("portrait: no FLUX unet among %s", UNET_CANDIDATES)
        return False
    need = [(f"{COMFY_ROOT}/models/unet", unet),
            (f"{COMFY_ROOT}/models/clip", CLIP_L),
            (f"{COMFY_ROOT}/models/clip", T5),
            (f"{COMFY_ROOT}/models/vae", VAE),
            (f"{COMFY_ROOT}/models/pulid", PULID)]
    for d, f in need:
        p = Path(d) / f
        if not p.is_file() or p.stat().st_size < 100_000:
            logger.info("portrait: missing %s", f)
            return False
    return True


def _analyser():
    """One configured insightface app. antelopev2, on the CPU deliberately.

    This runs while FLUX may be resident; handing insightface the CUDA
    provider as well is how the card went over its limit before.
    """
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="antelopev2",
                       root=f"{COMFY_ROOT}/models/insightface",
                       providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def _sharpness(patch) -> float:
    """Variance of the Laplacian — high for crisp edges, near zero for blur."""
    import cv2
    g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _yaw(kps) -> float:
    """Signed left/right head turn, from the five-point landmarks.

    The nose sits midway between the eyes on a frontal face and slides toward
    one of them as the head turns, so the normalised offset is a serviceable
    yaw proxy — and it costs nothing, where loading the 3D landmark model to
    read a real Euler angle costs another model on a card that has already
    shown it has no headroom.
    """
    (lx, _), (rx, _), (nx, _) = kps[0], kps[1], kps[2]
    span = float(rx - lx) or 1.0
    return max(-1.0, min(1.0, ((float(nx) - float(lx)) / span - 0.5) * 2.0))


def _norm(v):
    import numpy as np
    n = np.linalg.norm(v)
    return v / n if n else v


def _crop(img, bbox, pad: float, side: int = 768):
    import cv2
    x1, y1, x2, y2 = (int(v) for v in bbox)
    cw, ch = x2 - x1, y2 - y1
    mx, my = int(cw * pad), int(ch * pad)
    H, W = img.shape[:2]
    patch = img[max(0, y1 - my):min(H, y2 + my), max(0, x1 - mx):min(W, x2 + mx)]
    if patch.size == 0:
        return None
    return cv2.resize(patch, (side, side), interpolation=cv2.INTER_LANCZOS4)


def select_references(cands: list[dict], *, want: int = 4,
                      min_agreement: float = 0.5,
                      frontal: float = 0.12) -> tuple[list[dict], int]:
    """Choose which candidate frames become the reference set.

    Pure: every candidate is a dict of measurements (`emb`, `sharp`, `yaw`,
    `det`, `w`), no files and no models, so the policy can be tested without
    a GPU box to run it on. Returns the picks and how many frames were
    rejected as somebody else.
    """
    import numpy as np

    # Who is the owner. The face appearing consistently across the footage is
    # the subject; anyone who wandered through one frame disagrees with
    # everybody, and "biggest, most confident face" would average them in.
    E = np.stack([c["emb"] for c in cands])
    owner = E[int((E @ E.T).sum(axis=1).argmax())]
    kept = [c for c in cands if float(c["emb"] @ owner) >= min_agreement]
    strangers = len(cands) - len(kept)

    # Quality floor: drop the blurriest quarter. The node aligns to a 512px
    # chip, and a motion-blurred face upscaled into it invents detail.
    sharps = sorted(c["sharp"] for c in kept)
    floor = sharps[len(sharps) // 4] if len(sharps) >= 4 else 0.0
    pool = [c for c in kept if c["sharp"] >= floor] or kept

    # Spread the angles. Four frontal frames are nearly one frame, and the
    # average of one frame is that frame's accidents again.
    buckets: dict[str, list[dict]] = {"front": [], "left": [], "right": []}
    for c in pool:
        key = ("front" if abs(c["yaw"]) < frontal
               else ("left" if c["yaw"] < 0 else "right"))
        buckets[key].append(c)
    for b in buckets.values():
        b.sort(key=lambda c: c["det"] * c["w"] * (c["sharp"] ** 0.5), reverse=True)

    picked: list[dict] = []
    order = ("front", "left", "right")
    while len(picked) < want and any(buckets[k] for k in order):
        for k in order:
            if buckets[k] and len(picked) < want:
                picked.append(buckets[k].pop(0))
    return picked, strangers


def face_references(video: str, out_dir: str, *, want: int = 4,
                    samples: int = 24, pad: float = 0.9,
                    min_face_px: int = 150) -> list[str]:
    """The reference set from a single video. See gather_references."""
    return gather_references([video], out_dir, want=want, samples=samples,
                             pad=pad, min_face_px=min_face_px)


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def _candidates(app, img, pad: float, min_face_px: int, src: str) -> list[dict]:
    """Every usable face in one image, reduced to measurements."""
    out = []
    for f in app.get(img):
        w = float(f.bbox[2] - f.bbox[0])
        if w < min_face_px:
            continue
        patch = _crop(img, f.bbox, pad)
        if patch is None:
            continue
        out.append({"patch": patch, "w": w, "det": float(f.det_score),
                    "sharp": _sharpness(patch), "yaw": _yaw(f.kps),
                    "emb": _norm(f.normed_embedding), "src": src})
    return out


def gather_references(sources: list[str], out_dir: str, *, want: int = 4,
                      samples: int = 24, pad: float = 0.9,
                      min_face_px: int = 150) -> list[str]:
    """Build the reference set from any mix of stills and footage.

    One reference was the first mistake to fix and not the last. PuLID
    averages the identity embedding over however many images it is given, and
    a single frame carries that frame's accidents with it — the angle of the
    head, the half-formed vowel on the mouth, whatever the autofocus was
    doing. Averaging several frames cancels the accidents and leaves what is
    constant, which is the face. This is the node's own documented path to a
    closer likeness, and we were not using it.

    Stills and footage both get in, for opposite reasons. A still is posed and
    usually the largest face available; a video frame is smaller but caught
    mid-expression, and several across a clip is exactly the variety the
    averaging wants. Measured on this channel's own material the stills were
    the bigger faces (433px) and the video frames the sharper ones, so
    choosing one source over the other gives up something either way. They
    compete on the same measurements instead, and the set is picked on merit
    rather than on which folder the file came from.

    Three filters decide what gets in:

    size and sharpness, because the node aligns to a 512px chip and upscaling
    a small or motion-blurred face invents detail rather than supplying it;

    identity agreement, because footage can contain more than one person and
    "biggest, most confident face" will happily average a stranger into the
    owner. The medoid embedding is taken as the owner and outliers dropped;

    pose spread, because four frontal frames are nearly one frame.

    Each crop is then re-detected at the size it will be handed over. A
    reference PuLID cannot find is not an error there — it logs a warning and
    skips it, and if it skips them all it returns the model untouched and
    generates a stranger. Silent, plausible and wrong; so the check happens
    here, where it can still be acted on.
    """
    import subprocess
    import cv2

    app = _analyser()
    tmp_dir = Path(out_dir, "_frames")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    cands: list[dict] = []
    for src in sources:
        p = Path(src)
        if not p.is_file():
            logger.info("Face refs: %s not found — skipped", src)
            continue
        if p.suffix.lower() not in VIDEO_SUFFIXES:
            img = cv2.imread(str(p))
            if img is not None:
                cands += _candidates(app, img, pad, min_face_px, p.name)
            continue
        dur = _duration(str(p))
        if dur <= 0:
            logger.info("Face refs: no duration for %s — skipped", p.name)
            continue
        for i in range(samples):
            t = dur * (0.04 + 0.92 * i / max(1, samples - 1))
            tmp = tmp_dir / f"{p.stem}_{i:03d}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}",
                            "-i", str(p), "-frames:v", "1", str(tmp)],
                           capture_output=True)
            img = cv2.imread(str(tmp))
            if img is not None:
                cands += _candidates(app, img, pad, min_face_px,
                                     f"{p.name}@{t:.1f}s")

    if not cands:
        raise PortraitError(
            f"no face at least {min_face_px}px found in {len(sources)} "
            f"source(s) — cannot condition identity")

    picked, strangers = select_references(cands, want=want)
    if strangers:
        logger.info("Face refs: dropped %d frame(s) of someone else", strangers)

    # --- write, and prove each one survives detection -----------------------
    out: list[str] = []
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for n, c in enumerate(picked):
        dest = Path(out_dir, f"face_{n}.png")
        cv2.imwrite(str(dest), c["patch"])
        if not app.get(cv2.imread(str(dest))):
            logger.info("Face refs: %s did not survive the crop — dropped",
                        dest.name)
            dest.unlink(missing_ok=True)
            continue
        out.append(str(dest))
        logger.info("Face ref %d: %s  %dpx  yaw %+.2f  sharp %.0f",
                    n, c["src"], int(c["w"]), c["yaw"], c["sharp"])

    if not out:
        raise PortraitError("every candidate reference failed re-detection")
    return out


def face_reference(video: str, out_png: str, **kw) -> str:
    """The single best reference, for callers that only want one."""
    refs = face_references(video, str(Path(out_png).parent), want=1, **kw)
    Path(refs[0]).replace(out_png)
    return out_png


def reference_identity(refs: list[str]):
    """The mean normalised ArcFace embedding of the references.

    This is what a generated face is later compared against, so likeness stops
    being a matter of my opinion about a picture.
    """
    import cv2
    import numpy as np
    app = _analyser()
    vecs = []
    for r in refs:
        got = app.get(cv2.imread(r))
        if got:
            vecs.append(_norm(max(got, key=lambda f: f.bbox[2] - f.bbox[0])
                              .normed_embedding))
    if not vecs:
        raise PortraitError("no embeddings from the reference set")
    return _norm(np.mean(np.stack(vecs), axis=0))


def measure(image: str, identity) -> dict:
    """Score a generated cover against the reference identity.

    `cosine` is ArcFace similarity on the same model family that conditioned
    the generation. Treat it as ordinal, not absolute: it ranks two candidate
    covers reliably, which is all a sweep needs.

    `face_px` is there because a low cosine has two quite different causes and
    the knob to turn is different for each. If the rendered face is only 150px
    across, no id_weight recovers detail the sampler never had room to draw,
    and the fix is the framing in the scene brief, not the weight.
    """
    import cv2
    app = _analyser()
    img = cv2.imread(image)
    got = app.get(img) if img is not None else []
    if not got:
        return {"cosine": 0.0, "face_px": 0, "detected": False}
    f = max(got, key=lambda x: x.bbox[2] - x.bbox[0])
    return {"cosine": float(_norm(f.normed_embedding) @ identity),
            "face_px": int(f.bbox[2] - f.bbox[0]), "detected": True}


def identity_similarity(image: str, identity) -> float:
    """Just the cosine, for callers that only want the number."""
    return measure(image, identity)["cosine"]


def stage_face(image_path: str) -> str:
    """Put the face reference where ComfyUI's LoadImage can find it."""
    import shutil
    src = Path(image_path)
    if not src.is_file():
        raise PortraitError(f"face reference {image_path} not found")
    dest_dir = Path(COMFY_ROOT, "input")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"face_{src.stem}{src.suffix}"
    shutil.copy(src, dest)
    return dest.name


def _face_batch(names: list[str], first_id: int = 20) -> tuple[dict, list]:
    """LoadImage per reference, chained through ImageBatch into one tensor.

    ApplyPulidFlux takes a single IMAGE input and loops over its batch
    dimension, so several references reach it only if they are concatenated
    first. ImageBatch takes exactly two images, hence the chain rather than a
    single node. Every crop is written at 768x768, which matters: ImageBatch
    resizes mismatched inputs to the first one's shape, and a reference
    silently squashed to another aspect ratio is a reference that detects
    worse.
    """
    nodes: dict = {}
    for i, n in enumerate(names):
        nodes[str(first_id + i)] = {"class_type": "LoadImage",
                                    "inputs": {"image": n}}
    ref = [str(first_id), 0]
    for i in range(1, len(names)):
        nid = str(first_id + 100 + i)
        nodes[nid] = {"class_type": "ImageBatch",
                      "inputs": {"image1": ref, "image2": [str(first_id + i), 0]}}
        ref = [nid, 0]
    return nodes, ref


def _graph(*, prompt: str, face_images: list[str], width: int, height: int,
           steps: int, guidance: float, seed: int,
           id_weight: float, start_at: float, end_at: float) -> dict:
    """FLUX + PuLID, as a ComfyUI prompt graph."""
    face_nodes, face_ref = _face_batch(face_images)
    return {**face_nodes,
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": _resolve_unet() or UNET}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": T5, "clip_name2": CLIP_L,
                         "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "PulidFluxModelLoader",
              "inputs": {"pulid_file": PULID}},
        "5": {"class_type": "PulidFluxEvaClipLoader", "inputs": {}},
        "6": {"class_type": "PulidFluxInsightFaceLoader",
              "inputs": {"provider": "CUDA"}},
        "8": {"class_type": "ApplyPulidFlux",
              "inputs": {"model": ["1", 0], "pulid_flux": ["4", 0],
                         "eva_clip": ["5", 0], "face_analysis": ["6", 0],
                         "image": face_ref, "weight": id_weight,
                         "start_at": start_at, "end_at": end_at}},
        "9": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["2", 0], "text": prompt}},
        "10": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["9", 0], "guidance": guidance}},
        "11": {"class_type": "ConditioningZeroOut",
               "inputs": {"conditioning": ["9", 0]}},
        "12": {"class_type": "EmptyLatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        "13": {"class_type": "KSampler",
               "inputs": {"model": ["8", 0], "positive": ["10", 0],
                          "negative": ["11", 0], "latent_image": ["12", 0],
                          "seed": seed, "steps": steps, "cfg": 1.0,
                          "sampler_name": "euler", "scheduler": "simple",
                          "denoise": 1.0}},
        "14": {"class_type": "VAEDecode",
               "inputs": {"samples": ["13", 0], "vae": ["3", 0]}},
        "15": {"class_type": "SaveImage",
               "inputs": {"images": ["14", 0], "filename_prefix": "cover"}},
    }


def _require_free_vram(min_free_gb: float) -> None:
    """Refuse to load FLUX onto a card that is already occupied.

    The advisory /free below asks ComfyUI to drop ITS models and says nothing
    about the lip-sync and TTS services sharing this card. Twice a generation
    began on a partly-occupied card and took the whole machine off the
    network — no clean OOM, no dmesg trace, a hard lock. Failing here costs a
    run; not checking costs a reboot.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20).stdout.strip()
        used, total = (float(x) for x in out.split(",")[:2])
    except Exception as exc:                        # noqa: BLE001 — advisory
        logger.debug("vram check skipped: %s", str(exc)[:80])
        return
    free_gb = (total - used) / 1024
    if free_gb < min_free_gb:
        raise PortraitError(
            f"only {free_gb:.1f}GB VRAM free, need {min_free_gb:.0f} — another "
            f"model is resident; free it rather than risking the machine")
    logger.info("VRAM clear: %.1fGB free", free_gb)


def _run(graph: dict, *, timeout_s: int) -> str:
    """Submit a graph, wait for it, return the file it wrote.

    Both passes need this and neither needs its own copy of the polling.
    """
    t0 = time.time()
    res = _post("/prompt", {"prompt": graph, "client_id": uuid.uuid4().hex})
    pid = res.get("prompt_id")
    if not pid:
        raise PortraitError(f"ComfyUI rejected the graph: {str(res)[:300]}")

    while time.time() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=30) as r:
                hist = json.loads(r.read() or b"{}")
        except Exception:                           # noqa: BLE001 — keep polling
            time.sleep(4); continue
        entry = hist.get(pid)
        if entry:
            status = (entry.get("status") or {})
            if status.get("status_str") == "error" or (
                    status.get("completed") is False and status.get("messages")):
                raise PortraitError(f"generation failed: {json.dumps(status)[:400]}")
            for out in (entry.get("outputs") or {}).values():
                for im in out.get("images", []):
                    cand = Path(COMFY_ROOT, "output", im.get("subfolder", ""),
                                im["filename"])
                    if cand.is_file():
                        return str(cand)
        time.sleep(4)
    raise PortraitError(f"no image after {time.time() - t0:.0f}s")


def _free_gpu() -> None:
    """H3 and this cannot both be resident; whoever runs asks for the card."""
    try:
        _post("/free", {"unload_models": True, "free_memory": True})
        time.sleep(3)
    except Exception as exc:                        # noqa: BLE001 — best effort
        logger.debug("free failed: %s", exc)


def generate(*, scene: str, faces, out_path: str,
             width: int = 832, height: int = 1216, steps: int = 20,
             guidance: float = 3.5, seed: int = 0,
             id_weight: float = 1.05, start_at: float = 0.0,
             end_at: float = 1.0, traits: str = TRAITS,
             timeout_s: int = 900) -> str:
    """One cover photograph.

    Rendered at 832x1216 rather than the final 1080x1920. FLUX is trained near
    1MP and drifts badly above it — a taller latent produces duplicated torsos
    and a second face in the corner. Upscaling a correct 1MP frame is the
    cheaper mistake.

    `faces` is one path or several; several is better, and why is in
    face_references.
    """
    if not available():
        raise PortraitError("FLUX/PuLID weights are not installed")
    refs = [faces] if isinstance(faces, (str, Path)) else list(faces)
    if not refs:
        raise PortraitError("no face reference supplied")
    _free_gpu()
    _require_free_vram(min_free_gb=15.0)
    # Verify BEFORE spending two minutes of GPU. PuLID does not fail on an
    # undetectable face; it quietly generates someone else.
    try:
        import cv2
        _app = _analyser()
        usable = [r for r in refs if _app.get(cv2.imread(r))]
        if not usable:
            raise PortraitError(
                f"no face detected in any of {len(refs)} reference(s) — PuLID "
                f"would generate a stranger rather than fail")
        if len(usable) < len(refs):
            logger.info("Dropped %d undetectable reference(s)",
                        len(refs) - len(usable))
        refs = usable
    except PortraitError:
        raise
    except Exception as exc:                        # noqa: BLE001 — advisory
        logger.debug("face precheck skipped: %s", str(exc)[:90])

    names = [stage_face(r) for r in refs]
    full = f"{scene.strip().rstrip('.')}. {traits}. {STYLE}" if traits \
        else f"{scene.strip().rstrip('.')}. {STYLE}"
    graph = _graph(prompt=full, face_images=names, width=width, height=height,
                   steps=steps, guidance=guidance,
                   seed=seed or int(uuid.uuid4().int % 2**31),
                   id_weight=id_weight, start_at=start_at, end_at=end_at)

    t0 = time.time()
    produced = _run(graph, timeout_s=timeout_s)

    from PIL import Image
    img = Image.open(produced).convert("RGB")
    # Up to the cover's own size, once, with a good filter.
    img = img.resize((1080, int(1080 * img.height / img.width)), Image.LANCZOS)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=95)
    logger.info("Cover photo in %.0fs -> %s", time.time() - t0, Path(out_path).name)
    _free_gpu()
    return out_path


def _refine_graph(*, prompt: str, face_images: list[str], patch_image: str,
                  steps: int, guidance: float, seed: int, denoise: float,
                  id_weight: float) -> dict:
    """The face pass: the same PuLID-patched model, re-sampling one crop.

    Deliberately the smaller half of the job. ComfyUI encodes, samples and
    decodes; the crop and the paste-back happen in Python, where they can be
    tested without a GPU and where a feather is a feather rather than four
    more node types to get wrong.
    """
    face_nodes, face_ref = _face_batch(face_images)
    return {**face_nodes,
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": _resolve_unet() or UNET}},
        "2": {"class_type": "DualCLIPLoader",
              "inputs": {"clip_name1": T5, "clip_name2": CLIP_L,
                         "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "PulidFluxModelLoader",
              "inputs": {"pulid_file": PULID}},
        "5": {"class_type": "PulidFluxEvaClipLoader", "inputs": {}},
        "6": {"class_type": "PulidFluxInsightFaceLoader",
              "inputs": {"provider": "CUDA"}},
        "8": {"class_type": "ApplyPulidFlux",
              "inputs": {"model": ["1", 0], "pulid_flux": ["4", 0],
                         "eva_clip": ["5", 0], "face_analysis": ["6", 0],
                         "image": face_ref, "weight": id_weight,
                         "start_at": 0.0, "end_at": 1.0}},
        "9": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["2", 0], "text": prompt}},
        "10": {"class_type": "FluxGuidance",
               "inputs": {"conditioning": ["9", 0], "guidance": guidance}},
        "11": {"class_type": "ConditioningZeroOut",
               "inputs": {"conditioning": ["9", 0]}},
        "16": {"class_type": "LoadImage", "inputs": {"image": patch_image}},
        "17": {"class_type": "VAEEncode",
               "inputs": {"pixels": ["16", 0], "vae": ["3", 0]}},
        "13": {"class_type": "KSampler",
               "inputs": {"model": ["8", 0], "positive": ["10", 0],
                          "negative": ["11", 0], "latent_image": ["17", 0],
                          "seed": seed, "steps": steps, "cfg": 1.0,
                          "sampler_name": "euler", "scheduler": "simple",
                          "denoise": denoise}},
        "14": {"class_type": "VAEDecode",
               "inputs": {"samples": ["13", 0], "vae": ["3", 0]}},
        "15": {"class_type": "SaveImage",
               "inputs": {"images": ["14", 0], "filename_prefix": "coverface"}},
    }


def face_region(bbox, img_w: int, img_h: int, pad: float = 0.55) -> tuple:
    """A square box around a face, with margin, inside the image.

    Square because the patch is re-sampled at a square latent, and clamped by
    SHIFTING rather than shrinking: a box pushed past the edge slides back in
    at full size, so a face near the frame edge still gets a full-resolution
    pass instead of a smaller one.
    """
    x1, y1, x2, y2 = (float(v) for v in bbox)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    side = max(x2 - x1, y2 - y1) * (1.0 + 2.0 * pad)
    side = min(side, float(min(img_w, img_h)))
    left = min(max(0.0, cx - side / 2.0), img_w - side)
    top = min(max(0.0, cy - side / 2.0), img_h - side)
    return (int(left), int(top), int(left + side), int(top + side))


def feather_mask(size: int, frac: float = 0.12):
    """A soft-edged square mask for dropping the patch back in.

    A hard edge shows as a seam wherever the pass shifts skin tone by even a
    little, which it always does. The falloff is a blurred inset rectangle —
    fully opaque in the middle where the new detail is, fading to nothing
    before it reaches the original pixels.
    """
    from PIL import Image, ImageDraw, ImageFilter
    inset = max(1, int(size * frac))
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rectangle(
        [inset, inset, size - inset - 1, size - inset - 1], fill=255)
    return m.filter(ImageFilter.GaussianBlur(inset / 2.0))


def paste_face(base_path: str, patch_path: str, box: tuple, out_path: str,
               feather: float = 0.12) -> str:
    """Composite a refined face patch back into the full frame."""
    from PIL import Image
    base = Image.open(base_path).convert("RGB")
    w = box[2] - box[0]
    patch = Image.open(patch_path).convert("RGB").resize((w, w), Image.LANCZOS)
    base.paste(patch, (box[0], box[1]), feather_mask(w, feather))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    base.save(out_path, quality=95)
    return out_path


def refine_face(*, image: str, faces, out_path: str, denoise: float = 0.40,
                steps: int = 20, guidance: float = 3.5, id_weight: float = 1.05,
                seed: int = 0, side: int = 768, pad: float = 0.55,
                feather: float = 0.12, traits: str = TRAITS,
                timeout_s: int = 600) -> str:
    """Re-sample the face at full resolution and drop it back in.

    The base render puts about 230 pixels of face in a 832px frame. PuLID
    aligns identity to a 512px chip, so more than half the detail it is
    conditioning on has nowhere to land — the sampler is being asked to draw
    a likeness at a size that cannot hold one. That is a resolution ceiling,
    and no id_weight setting lifts it.

    So the face is cropped out, re-sampled on its own at 768, and composited
    back. Low denoise: the pose, the lighting and the expression are already
    right and the pass is only there to spend pixels on the identity.
    """
    import cv2
    refs = [faces] if isinstance(faces, (str, Path)) else list(faces)
    app = _analyser()
    img = cv2.imread(image)
    if img is None:
        raise PortraitError(f"cannot read {image}")
    got = app.get(img)
    if not got:
        raise PortraitError("no face in the base render to refine")
    f = max(got, key=lambda x: x.bbox[2] - x.bbox[0])
    H, W = img.shape[:2]
    box = face_region(f.bbox, W, H, pad)
    logger.info("Face pass: %dpx crop -> %dpx sample", box[2] - box[0], side)

    from PIL import Image
    crop_path = str(Path(out_path).with_name(f"{Path(out_path).stem}_crop.png"))
    Image.open(image).convert("RGB").crop(box).resize(
        (side, side), Image.LANCZOS).save(crop_path)

    _free_gpu()
    _require_free_vram(min_free_gb=15.0)
    graph = _refine_graph(
        prompt=(f"a close portrait of his face, {traits}, natural skin "
                f"texture, sharp eyes, warm tungsten light, 85mm lens, "
                f"photorealistic"),
        face_images=[stage_face(r) for r in refs],
        patch_image=stage_face(crop_path), steps=steps, guidance=guidance,
        seed=seed or int(uuid.uuid4().int % 2**31), denoise=denoise,
        id_weight=id_weight)
    produced = _run(graph, timeout_s=timeout_s)
    out = paste_face(image, produced, box, out_path, feather)
    _free_gpu()
    logger.info("Refined face -> %s", Path(out).name)
    return out


RESTART = "/home/vishalan/comfy_restart.sh"


def restart_comfy(*, wait_s: int = 180) -> bool:
    """Bounce ComfyUI and wait for it to answer again.

    A single generation on a cold card completes; a second one on the same
    warm process has twice taken the machine off the network, with no OOM and
    nothing in dmesg. Whatever is leaking, a fresh process does not have it —
    so the sweep below pays 30 seconds of reload per candidate rather than
    gambling the box on each one.
    """
    import subprocess
    if not Path(RESTART).is_file():
        logger.info("No %s — not restarting", RESTART)
        return False
    subprocess.run(["bash", RESTART], capture_output=True, timeout=60)
    for _ in range(wait_s // 3):
        time.sleep(3)
        try:
            with urllib.request.urlopen(f"{COMFY}/system_stats", timeout=5):
                return True
        except Exception:                           # noqa: BLE001 — still booting
            continue
    logger.warning("ComfyUI did not come back within %ds", wait_s)
    return False


def best_of(*, scene: str, faces, out_path: str,
            trials=((1.05, 0), (1.20, 0), (0.90, 0)),
            restart_between: bool = True, **kw) -> dict:
    """Generate several covers and keep the one that looks most like him.

    Likeness was being judged by me looking at a picture, which is neither
    repeatable nor honest about small differences. Here each candidate is
    scored by ArcFace cosine against the reference identity and the best one
    wins, so raising id_weight can be shown to help or shown not to.

    Returns the winner and every score, because the scores are the finding —
    if they are all within a hair of each other the knob is not the problem
    and the reference set is.
    """
    identity = reference_identity(
        [faces] if isinstance(faces, (str, Path)) else list(faces))
    results, best, best_score = [], None, -1.0
    tmp = Path(out_path).with_suffix("")
    for i, (w, s) in enumerate(trials):
        if restart_between and i:
            restart_comfy()
        cand = f"{tmp}_w{w:.2f}_s{s}.jpg"
        try:
            generate(scene=scene, faces=faces, out_path=cand,
                     id_weight=w, seed=s, **kw)
        except PortraitError as exc:
            logger.warning("trial w=%.2f failed: %s", w, str(exc)[:120])
            results.append({"id_weight": w, "seed": s, "score": None,
                            "error": str(exc)[:200]})
            continue
        m = measure(cand, identity)
        score = m["cosine"]
        results.append({"id_weight": w, "seed": s, "score": round(score, 4),
                        "face_px": m["face_px"], "path": cand})
        logger.info("trial w=%.2f seed=%d -> cosine %.3f (face %dpx)",
                    w, s, score, m["face_px"])
        if score > best_score:
            best, best_score = cand, score

    if best is None:
        raise PortraitError("every trial failed")
    Path(best).replace(out_path)
    logger.info("Best likeness %.3f -> %s", best_score, Path(out_path).name)
    return {"path": out_path, "score": round(best_score, 4), "trials": results}


async def scene_for(story: dict, ask) -> str:
    """A scene brief for this story, in the grid's language.

    Asked for as a PHOTOGRAPH, never as a concept. The reference covers are
    someone in a room with an object; a brief that says "innovation" or
    "the future of AI" returns a stock abstraction with no person in it.
    """
    title = story.get("title", "")
    subject = (story.get("subject_domains") or ["the subject"])[0]
    artifact = story.get("artifact_label") or title
    prompt = (
        "Describe ONE photograph for the cover of a short video.\n\n"
        f"  story: {title}\n"
        f"  subject: {subject}\n"
        f"  the object in shot: {artifact}\n\n"
        "A young man is in a room, presenting the object to camera — holding "
        "a printed sheet, pointing at a laptop screen, holding up a phone, or "
        "gesturing at something pinned to the wall. Choose whichever suits "
        "this story, and choose the ROOM too: a study with bookshelves, a "
        "bedroom, a desk by a window, a living room in the evening.\n\n"
        "Write what the CAMERA SEES: where he is, what he is doing with his "
        "hands, what the object physically is, what is behind him. Do not "
        "describe his face or his identity — that is fixed elsewhere. No "
        "readable text, no logos, no brand marks in the scene. No abstractions. "
        "35 words or fewer, one sentence, plain prose."
    )
    try:
        out = (await ask(prompt) or "").strip()
        return " ".join(out.split())[:340]
    except Exception as exc:                        # noqa: BLE001 — optional
        logger.info("scene brief failed (%s) — using a default", str(exc)[:90])
        return ("A young man sits at a wooden desk in a study, holding up a "
                "printed sheet of paper toward the camera, bookshelves and a "
                "warm lamp behind him")
