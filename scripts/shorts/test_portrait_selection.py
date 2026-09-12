"""Which frames become the face reference set.

The policy is the part that decides whether PuLID sees the owner four times
from three angles or sees one blurry frame and a stranger, and it is the part
that can be checked without a GPU. So it is pure, and this is its test.

    python3 -m pytest scripts/shorts/test_portrait_selection.py
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from shorts.portrait import select_references, _yaw


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
