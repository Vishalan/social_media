"""Match the subject's typographic character with a font we may actually use.

A brand's real typeface is nearly always proprietary. Probing three subjects'
own stylesheets returned "Anthropic Sans", "Build Week Digital" and
"TwitterChirp" — bespoke faces, licensed to their owners. Downloading one and
burning it into a monetised video is a licensing violation, so the useful
question is not "what font do they use" but "what KIND of font do they use".

That question has an answer worth acting on. A brand whose site is set in a
geometric sans and one set in a didone serif do not look alike, and matching
the category with a licensed face carries most of the resemblance at none of
the risk. It is the same trade the palette already makes: borrow the
character, not the asset.

Everything in CATALOGUE is SIL Open Font License — commercial use, no
attribution obligation in the rendered video.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .net import BROWSER_UA

logger = logging.getLogger(__name__)

FONT_DIR = Path("/opt/commoncreed/assets/fonts")

# Category -> family, Google Fonts directory, and why it belongs to that class.
#
# One face per category, chosen for a display role at phone scale: generous
# x-height, unambiguous letterforms, and a heavy weight that still has
# structure. A face that is characterful at 200px on a desktop is frequently
# mush at 60px on a phone.
CATALOGUE: dict[str, dict] = {
    "geometric_sans": {
        "family": "Outfit", "dir": "outfit",
        "why": "even circular bowls, single-storey a — Futura's lineage",
    },
    "grotesque_sans": {
        "family": "Inter", "dir": "inter",
        "why": "neutral, tight apertures — the Helvetica/Univers lineage",
    },
    "humanist_sans": {
        "family": "Source Sans 3", "dir": "sourcesans3",
        "why": "calligraphic stress, open apertures, warmer than a grotesque",
    },
    "transitional_serif": {
        "family": "Source Serif 4", "dir": "sourceserif4",
        "why": "moderate contrast, bracketed serifs — a reading serif",
    },
    "didone_serif": {
        "family": "Playfair Display", "dir": "playfairdisplay",
        "why": "extreme thick-thin contrast, hairline serifs — editorial",
    },
    "slab_serif": {
        "family": "Roboto Slab", "dir": "robotoslab",
        "why": "square unbracketed serifs, industrial",
    },
    "mono": {
        "family": "JetBrains Mono", "dir": "jetbrainsmono",
        "why": "fixed pitch, engineered",
    },
}
DEFAULT = "grotesque_sans"

_CSS_LINK = re.compile(r'<link[^>]+href="([^"]+\.css[^"]*)"', re.I)
_FACE = re.compile(r'@font-face[^}]*?font-family\s*:\s*["\']?([^;"\'}]+)', re.I)
_FAMILY = re.compile(r'font-family\s*:\s*([^;}"\']+)', re.I)

_IGNORE = {
    "inherit", "initial", "unset", "sans-serif", "serif", "monospace",
    "system-ui", "ui-monospace", "ui-sans-serif", "cursive", "fantasy",
    "-apple-system", "blinkmacsystemfont", "emoji",
}


def _get(url: str, limit: int = 400_000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read(limit).decode("utf-8", "ignore")


def declared_families(site: str, *, max_css: int = 4) -> list[str]:
    """Font families a site declares, most specific first.

    @font-face names come first because they are what the brand actually
    ships; a bare font-family stack is frequently a fallback chain that says
    more about the CSS reset than about the brand.
    """
    try:
        html = _get(site)
    except Exception as exc:                        # noqa: BLE001 — optional
        # INFO, not debug. This failing is the difference between typography
        # sourced from the subject and the house default, and it failed once
        # in a real run while succeeding when tried by hand a minute later —
        # a transient that left no trace of why the story got Inter.
        logger.info("typeface: could not read %s (%s) — falling back",
                    site, str(exc)[:90])
        return []
    blob = html
    for href in _CSS_LINK.findall(html)[:max_css]:
        try:
            blob += _get(urllib.parse.urljoin(site, href), 300_000)
        except Exception:                           # noqa: BLE001 — partial ok
            pass

    out, seen = [], set()
    for name in _FACE.findall(blob) + _FAMILY.findall(blob):
        n = name.split(",")[0].strip().strip("\"'")
        k = n.lower()
        if (not n or k in seen or k in _IGNORE or len(n) > 40
                or n.startswith("var(") or k.startswith("katex")
                or "icon" in k):
            continue
        seen.add(k)
        out.append(n)
    return out[:8]


async def classify(families: list[str], *, ask=None) -> str:
    """Which CATALOGUE category these families belong to.

    Delegated to the model rather than pattern-matched on the name. A name
    carries almost no signal — "Anthropic Serif" is legible but "TwitterChirp"
    and "Build Week Digital" are not, and a keyword rule would need extending
    for every brand ever encountered. The model has seen these faces.
    """
    if not families:
        return DEFAULT

    # Strip code faces before ANY classification, model or heuristic.
    #
    # The filter was on the fallback path only, and the model then classified
    # OpenAI as monospace off "Build Week Digital, Courier New" — Courier is
    # the code fallback in their reset, not their display face. Telling the
    # model to ignore code fonts was not enough; when one of two candidates is
    # a monospace it dominates the answer. Removing them from the question is
    # more reliable than asking for them to be discounted.
    _CODE = ("mono", "code", "courier", "consolas", "menlo", "monaco",
             "sfmono", "typewriter")
    display = [f for f in families if not any(w in f.lower() for w in _CODE)]
    if not display:
        return "mono"
    families = display

    if ask is None:
        # Code fonts are declared FIRST on plenty of sites — Anthropic ships
        # JetBrains Mono ahead of its own display faces — so taking the head
        # of the list classified a brand by the font it sets code samples in.
        # Drop the monospace entries unless they are all there is.
        low = " ".join(families).lower()
        if "serif" in low and "sans" not in low.split("serif")[0][-6:]:
            return "transitional_serif"
        return DEFAULT
    cats = "\n".join(f"  {k}: {v['why']}" for k, v in CATALOGUE.items())
    prompt = (
        "A brand's website declares these typefaces, most specific first:\n\n"
        f"  {', '.join(families)}\n\n"
        "The list is in declaration order, which is NOT importance order — a "
        "code font is frequently declared first. Classify the brand's PRIMARY "
        "DISPLAY typeface, the one headings are set in, into exactly one of "
        f"these categories:\n\n{cats}\n\n"
        "Judge by how the face actually looks if you know it, and by the "
        "brand's typographic character otherwise. Ignore icon fonts, code "
        "fonts used only for code samples, and generic fallbacks. Reply with "
        "the category key alone, nothing else."
    )
    try:
        got = (await ask(prompt) or "").strip().lower()
    except Exception as exc:                        # noqa: BLE001 — optional
        logger.debug("typeface classify failed: %s", str(exc)[:90])
        return DEFAULT
    for key in CATALOGUE:
        if key in got:
            return key
    return DEFAULT


def _gf_url(dirname: str, filename: str) -> str:
    return (f"https://github.com/google/fonts/raw/main/ofl/{dirname}/"
            f"{urllib.parse.quote(filename)}")


def ensure(category: str) -> dict:
    """Local paths for a category, downloading the family if needed.

    Missing weights fall back to whatever the family did provide, and the
    whole thing falls back to Inter, so a fetch failure degrades the look
    rather than the build.
    """
    spec = CATALOGUE.get(category) or CATALOGUE[DEFAULT]
    fam = spec["family"]
    slug = fam.replace(" ", "")
    FONT_DIR.mkdir(parents=True, exist_ok=True)

    want = {
        "regular": [f"{slug}-Regular.ttf", f"{slug}[wght].ttf"],
        "bold": [f"{slug}-Bold.ttf", f"{slug}-SemiBold.ttf", f"{slug}[wght].ttf"],
        "italic_bold": [f"{slug}-BoldItalic.ttf", f"{slug}-Italic[wght].ttf",
                        f"{slug}-Italic.ttf"],
    }
    got: dict[str, str] = {}
    for role, names in want.items():
        for n in names:
            dst = FONT_DIR / n
            if dst.is_file() and dst.stat().st_size > 40_000:
                got[role] = str(dst)
                break
            try:
                req = urllib.request.Request(_gf_url(spec["dir"], n),
                                             headers={"User-Agent": BROWSER_UA})
                data = urllib.request.urlopen(req, timeout=60).read()
            except Exception:                       # noqa: BLE001 — try next
                continue
            # A 404 from the fonts repo is an HTML page large enough to pass a
            # naive size check, and it renders as a system fallback silently.
            if len(data) < 40_000 or data[:5] in (b"<!DOC", b"<html"):
                continue
            dst.write_bytes(data)
            got[role] = str(dst)
            break

    if not got:
        logger.info("typeface: %s unavailable — staying on Inter", fam)
        return {"family": "Inter", "category": DEFAULT,
                "regular": str(FONT_DIR / "Inter-Regular.ttf"),
                "bold": str(FONT_DIR / "Inter-Black.ttf"),
                "italic_bold": str(FONT_DIR / "Inter-Black.ttf")}

    got.setdefault("regular", got.get("bold", ""))
    got.setdefault("bold", got["regular"])
    got.setdefault("italic_bold", got["bold"])
    got["family"] = fam
    got["category"] = category
    logger.info("typeface: %s -> %s", category, fam)
    return got


def _pin_heavy(path: str, out: str, wght: int = 800) -> str:
    """Pin a variable font at a heavy instance.

    freetype renders a variable font at its DEFAULT instance, which is almost
    always Regular — so a variable file used directly comes out light at every
    size, and no amount of scaling fixes it.
    """
    if "[wght]" not in path:
        return path
    try:
        from fontTools import ttLib
        from fontTools.varLib import instancer
        f = ttLib.TTFont(path)
        if "wght" not in {a.axisTag for a in f["fvar"].axes}:
            return path
        instancer.instantiateVariableFont(f, {"wght": wght}).save(out)
        return out
    except Exception as exc:                        # noqa: BLE001 — optional
        logger.debug("pin failed for %s: %s", path, str(exc)[:80])
        return path


async def resolve(domains: list[str], *, ask=None) -> dict:
    """The full typeface decision for one story's subject."""
    fams: list[str] = []
    for d in (domains or [])[:2]:
        site = d if d.startswith("http") else f"https://{d}"
        fams += declared_families(site)
        if fams:
            break
    if fams:
        logger.info("typeface: %s declares %s",
                    (domains or ["?"])[0], ", ".join(fams[:4]))
    else:
        logger.info("typeface: no families read from %s — using the default "
                    "category", ", ".join(domains or ["(none)"]))
    cat = await classify(fams, ask=ask)
    got = ensure(cat)
    for role, wght in (("bold", 800), ("italic_bold", 800), ("regular", 400)):
        p = got.get(role, "")
        if "[wght]" in p:
            stem = Path(p).stem.split("[")[0]
            got[role] = _pin_heavy(p, str(FONT_DIR / f"{stem}-p{wght}.ttf"), wght)
    got["declared"] = fams[:4]
    return got
