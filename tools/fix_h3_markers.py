"""Strip the packager's trailing marker from the H3 weight files.

The community GGUF repo appends a build marker to the end of each file —
"\nL2P_bypass_<name>_<timestamp>\n". The bytes are in the upstream artifact
(the local files are byte-exact against HF metadata), but safetensors is strict
about the whole file being covered by the header and refuses to load.
"""
import json, os, struct

FILES = [
    "/home/vishalan/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors",
    "/home/vishalan/ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors",
    "/home/vishalan/ComfyUI/models/unet/MiniMax-H3-FL2VA-Q4_K_M.gguf",
    "/home/vishalan/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
]

for p in FILES:
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        tail = f.read(4)
        f.seek(max(0, size - 96))
        marker = f.read(96)
    has_marker = b"L2P_bypass" in marker
    name = os.path.basename(p)

    if p.endswith(".safetensors"):
        with open(p, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            hdr = json.loads(f.read(n))
        end = max((v["data_offsets"][1] for k, v in hdr.items()
                   if k != "__metadata__" and isinstance(v, dict)), default=0)
        want = 8 + n + end
        if want != size:
            os.truncate(p, want)
            print(f"  {name[:46]:48s} trimmed {size - want} bytes  (marker={has_marker})")
        else:
            print(f"  {name[:46]:48s} already clean")
    else:
        # GGUF has no declared total length, so only strip an actual marker.
        if has_marker:
            idx = marker.rfind(b"\nL2P_bypass")
            cut = size - (len(marker) - idx)
            os.truncate(p, cut)
            print(f"  {name[:46]:48s} trimmed {size - cut} bytes (GGUF marker)")
        else:
            print(f"  {name[:46]:48s} no marker (magic={tail!r})")
