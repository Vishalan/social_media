"""The parts of the cover generator that need no GPU to check.

Which frames become the reference set decides whether PuLID sees the owner
four times from three angles or sees one blurry frame and a stranger. Where
the face pass crops and how it blends back decides whether the extra detail
arrives without a seam. Both are pure, so both are tested here rather than
discovered on a box that takes ten minutes to reload.

    python3 scripts/shorts/test_portrait.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from shorts.portrait import (select_references, _yaw, face_region,
                             feather_mask, paste_face, _graph, _refine_graph)


def cand(*, who="owner", yaw=0.0, sharp=100.0, det=0.9, w=300.0, tag=""):
    """A candidate frame reduced to the numbers the policy actually reads."""
    base = {"owner": [1.0, 0.0, 0.0], "stranger": [0.0, 1.0, 0.0]}[who]
    v = np.array(base, dtype=float)
    return {"emb": v / np.linalg.norm(v), "yaw": yaw, "sharp": sharp,
            "det": det, "w": w, "tag": tag or f"{who}:{yaw:+.2f}"}


def test_strangers_are_dropped():
    cands = [cand(who="owner", yaw=y) for y in (0.0, 0.02, -0.3, 0.3)]
    cands += [cand(who="stranger", yaw=0.0, w=900.0, det=0.99)]
    picked, strangers = select_references(cands, want=4)
    assert strangers == 1
    assert all(c["tag"].startswith("owner") for c in picked), \
        "a stranger reached the reference set"


def test_stranger_wins_on_size_but_still_loses():
    # The old rule was det_score * width, which this stranger wins outright.
    cands = [cand(who="owner", yaw=y, w=200.0) for y in (0.0, -0.3, 0.3)]
    big = cand(who="stranger", yaw=0.0, w=2000.0, det=1.0, tag="the-stranger")
    picked, _ = select_references(cands + [big], want=3)
    assert "the-stranger" not in {c["tag"] for c in picked}


def test_angles_are_spread_before_a_bucket_repeats():
    cands = ([cand(who="owner", yaw=0.0, sharp=500.0, tag=f"front{i}") for i in range(5)]
             + [cand(who="owner", yaw=-0.4, sharp=100.0, tag="left0")]
             + [cand(who="owner", yaw=0.5, sharp=100.0, tag="right0")])
    picked, _ = select_references(cands, want=3)
    tags = {c["tag"] for c in picked}
    assert "left0" in tags and "right0" in tags, \
        f"sharper frontal frames crowded out the angles: {tags}"


def test_falls_back_to_frontal_when_thats_all_there_is():
    cands = [cand(who="owner", yaw=0.01 * i, sharp=100.0 + i, tag=f"f{i}")
             for i in range(6)]
    picked, _ = select_references(cands, want=4)
    assert len(picked) == 4


def test_want_is_a_ceiling_not_a_quota():
    picked, _ = select_references([cand(who="owner")], want=4)
    assert len(picked) == 1


def test_blurriest_quarter_is_dropped():
    cands = [cand(who="owner", yaw=0.0, sharp=s, tag=f"s{s}")
             for s in (1.0, 2.0, 900.0, 1000.0)]
    picked, _ = select_references(cands, want=2)
    assert {c["tag"] for c in picked} == {"s900.0", "s1000.0"}


def test_yaw_reads_the_turn_from_landmarks():
    # kps order is left eye, right eye, nose, mouth corners.
    frontal = [(0.0, 0), (100.0, 0), (50.0, 40), (20, 70), (80, 70)]
    turned_r = [(0.0, 0), (100.0, 0), (80.0, 40), (20, 70), (80, 70)]
    turned_l = [(0.0, 0), (100.0, 0), (20.0, 40), (20, 70), (80, 70)]
    assert math.isclose(_yaw(frontal), 0.0, abs_tol=1e-9)
    assert _yaw(turned_r) > 0.4
    assert _yaw(turned_l) < -0.4


def test_yaw_survives_degenerate_landmarks():
    same = [(50.0, 0), (50.0, 0), (50.0, 40), (20, 70), (80, 70)]
    assert -1.0 <= _yaw(same) <= 1.0


# --- the face pass ---------------------------------------------------------

def test_face_region_is_square_and_centred():
    box = face_region((400, 300, 600, 560), 1080, 1578, pad=0.55)
    w, h = box[2] - box[0], box[3] - box[1]
    assert w == h, f"not square: {box}"
    assert abs((box[0] + box[2]) / 2 - 500) < 2
    assert abs((box[1] + box[3]) / 2 - 430) < 2


def test_face_region_slides_inside_the_frame_at_full_size():
    # A face against the left edge. The box must slide right, not shrink —
    # a smaller box means a lower-resolution pass exactly where detail matters.
    wide = face_region((10, 300, 210, 560), 1080, 1578, pad=0.55)
    free = face_region((400, 300, 600, 560), 1080, 1578, pad=0.55)
    assert wide[2] - wide[0] == free[2] - free[0], "box shrank at the edge"
    assert wide[0] >= 0 and wide[2] <= 1080


def test_face_region_never_leaves_the_image():
    for bbox in ((0, 0, 200, 200), (900, 1400, 1079, 1577), (0, 1500, 100, 1577)):
        x1, y1, x2, y2 = face_region(bbox, 1080, 1578)
        assert 0 <= x1 < x2 <= 1080 and 0 <= y1 < y2 <= 1578, (bbox, (x1, y1, x2, y2))


def test_face_region_caps_at_the_short_side():
    box = face_region((0, 0, 900, 900), 1000, 600, pad=1.0)
    assert box[2] - box[0] <= 600 and box[3] - box[1] <= 600


def test_feather_mask_is_opaque_inside_and_clear_outside():
    m = feather_mask(200, 0.12)
    assert m.getpixel((100, 100)) == 255, "centre is not fully opaque"
    assert m.getpixel((0, 0)) < 12, "corner is not transparent"
    assert m.size == (200, 200)


def test_paste_back_of_an_unchanged_crop_is_invisible():
    # The blend must be lossless when the patch carries no change. If this
    # drifts, every refined cover has a faint square around the face.
    import tempfile
    from PIL import Image, ImageChops
    import numpy as np

    with tempfile.TemporaryDirectory() as d:
        base_p = f"{d}/base.png"
        rng = np.random.default_rng(0)
        base = Image.fromarray(
            rng.integers(0, 255, (400, 300, 3), dtype=np.uint8))
        base.save(base_p)

        box = (60, 80, 220, 240)
        patch_p = f"{d}/patch.png"
        base.crop(box).save(patch_p)

        out = paste_face(base_p, patch_p, box, f"{d}/out.png", feather=0.12)
        diff = ImageChops.difference(Image.open(out).convert("RGB"), base)
        assert max(diff.getextrema()[c][1] for c in range(3)) <= 1, \
            "identity paste changed the image"


def test_paste_back_lands_in_the_right_place():
    import tempfile
    from PIL import Image

    with tempfile.TemporaryDirectory() as d:
        base = Image.new("RGB", (400, 300), (0, 0, 0))
        base.save(f"{d}/base.png")
        Image.new("RGB", (160, 160), (255, 0, 0)).save(f"{d}/patch.png")
        box = (60, 80, 220, 240)
        out = Image.open(paste_face(f"{d}/base.png", f"{d}/patch.png", box,
                                    f"{d}/out.png")).convert("RGB")
        assert out.getpixel((140, 160))[0] > 200, "patch centre missing"
        assert out.getpixel((10, 10)) == (0, 0, 0), "patch bled outside the box"


# --- graph wiring ----------------------------------------------------------

def _edges_resolve(g):
    for nid, node in g.items():
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in g, f"{nid}.{k} -> missing node {v[0]}"


def _walk_images(g, ref, seen):
    node = g[ref[0]]
    if node["class_type"] == "LoadImage":
        seen.append(node["inputs"]["image"])
    elif node["class_type"] == "ImageBatch":
        _walk_images(g, node["inputs"]["image1"], seen)
        _walk_images(g, node["inputs"]["image2"], seen)
    else:
        raise AssertionError(f"unexpected {node['class_type']} in the image chain")
    return seen


def test_every_reference_reaches_pulid_in_order():
    for n in (1, 2, 4):
        g = _graph(prompt="x", face_images=[f"f{i}.png" for i in range(n)],
                   width=832, height=1216, steps=20, guidance=3.5, seed=7,
                   id_weight=1.05, start_at=0.0, end_at=1.0)
        _edges_resolve(g)
        assert _walk_images(g, g["8"]["inputs"]["image"], []) == \
            [f"f{i}.png" for i in range(n)]


def test_sampler_reads_the_patched_model_not_the_raw_unet():
    for g in (_graph(prompt="x", face_images=["a.png"], width=832, height=1216,
                     steps=20, guidance=3.5, seed=1, id_weight=1.2,
                     start_at=0.1, end_at=0.9),
              _refine_graph(prompt="x", face_images=["a.png"],
                            patch_image="p.png", steps=20, guidance=3.5,
                            seed=1, denoise=0.4, id_weight=1.2)):
        assert g["13"]["inputs"]["model"] == ["8", 0]


def test_refine_pass_samples_the_crop_and_keeps_identity_separate():
    g = _refine_graph(prompt="x", face_images=["a.png", "b.png"],
                      patch_image="crop.png", steps=20, guidance=3.5,
                      seed=1, denoise=0.4, id_weight=1.1)
    _edges_resolve(g)
    # The crop is what gets re-sampled...
    assert g["17"]["inputs"]["pixels"] == ["16", 0]
    assert g["16"]["inputs"]["image"] == "crop.png"
    assert g["13"]["inputs"]["latent_image"] == ["17", 0]
    # ...and it must NOT have crept into the identity batch.
    assert _walk_images(g, g["8"]["inputs"]["image"], []) == ["a.png", "b.png"]
    assert 0.0 < g["13"]["inputs"]["denoise"] < 1.0, "a face pass at full denoise"


# --- waiting for the card ---------------------------------------------------

def _with_vram(readings, fn):
    """Run fn with _free_vram_gb returning each reading in turn, then the last."""
    import shorts.portrait as P
    seq = list(readings)
    calls = []

    def fake():
        calls.append(1)
        return seq.pop(0) if len(seq) > 1 else seq[0]

    real_vram, real_sleep = P._free_vram_gb, P.time.sleep
    P._free_vram_gb, P.time.sleep = fake, lambda _s: None
    try:
        return fn(), len(calls)
    finally:
        P._free_vram_gb, P.time.sleep = real_vram, real_sleep


def test_vram_guard_waits_for_a_card_that_frees_up():
    # A card mid-reclaim after kill -9: busy, busy, then free. Refusing on the
    # first reading would fail every sweep on its second trial.
    from shorts.portrait import _require_free_vram
    _, calls = _with_vram([2.0, 8.0, 21.0],
                          lambda: _require_free_vram(15.0, wait_s=60))
    assert calls >= 3, f"gave up after {calls} reading(s)"


def test_vram_guard_still_refuses_a_card_that_stays_busy():
    from shorts.portrait import _require_free_vram, PortraitError
    def go():
        try:
            _require_free_vram(15.0, wait_s=0)
            return "allowed"
        except PortraitError:
            return "refused"
    verdict, _ = _with_vram([3.0], go)
    assert verdict == "refused", "let a generation start on an occupied card"


def test_vram_guard_passes_when_the_card_cannot_be_queried():
    # No nvidia-smi is not evidence of a busy card; it must not block the run.
    from shorts.portrait import _require_free_vram
    verdict, _ = _with_vram([None], lambda: _require_free_vram(15.0, wait_s=0) or "ok")
    assert verdict == "ok"


if __name__ == "__main__":
    import traceback
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except Exception:
                fails += 1
                print(f"  FAIL  {name}")
                traceback.print_exc()
    print("all passed" if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
