"""Render a gallery of REALISTIC sample documents for the app's "Upload documents" tab,
plus a manifest the frontend uses to one-click prefill the file picker AND the claim form.

Each example is a real claim shape (form values + matching documents) curated to land on a
specific outcome through the LIVE pipeline (OCR → DeepSeek → deterministic engine):

    APPROVED      clean consultation · network-hospital discount · dental partial
    REJECTED      diabetes waiting period · excluded (bariatric) · per-claim limit · MRI no pre-auth
    HUMAN REVIEW  high-value auto-review (>₹25k) · same-day velocity (seeds prior claims)

The documents are drawn to look like genuine Indian hospital/clinic paperwork — letterhead
with address + GSTIN, an itemised table, a totals box, a round "PAID" stamp and a signature
line — while staying crisp enough for Tesseract. Form values match each document's content
(patient, amount, date) so the claim/document consistency checks pass.

Output:
    frontend/public/samples/<id>/<file>.png   the rendered images (served at /samples/...)
    frontend/public/samples/manifest.json     [{id, bucket, label, description, form, files[], seed?}]

Run:  uv run python -m eval.sample_gallery
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_REPO = Path(__file__).resolve().parents[2]
OUT = _REPO / "frontend" / "public" / "samples"

# ── palette ──────────────────────────────────────────────────────────────────────
INK = (24, 28, 35)
MUTE = (96, 104, 116)
LINE = (208, 214, 222)
ZEBRA = (244, 246, 249)
PAPER = (255, 255, 255)
STAMP = (38, 110, 78)  # green "PAID" seal


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        ["Arial Bold.ttf", "Helvetica.ttc", "DejaVuSans-Bold.ttf"]
        if bold
        else ["Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf"]
    )
    roots = ["/System/Library/Fonts/Supplemental/", "/Library/Fonts/", "/usr/share/fonts/truetype/dejavu/", ""]
    for root in roots:
        for n in names:
            try:
                return ImageFont.truetype(root + n, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _w(draw: ImageDraw.ImageDraw, text: str, font: Any) -> int:
    return int(draw.textlength(text, font=font))


def _inr(n: int) -> str:
    return f"Rs {n:,}"


def _stamp(img: Image.Image, cx: int, cy: int, label: str = "PAID") -> None:
    """A round green ink stamp, drawn slightly rotated for authenticity."""
    d = 150
    seal = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    sd = ImageDraw.Draw(seal)
    sd.ellipse([4, 4, d - 4, d - 4], outline=STAMP, width=3)
    sd.ellipse([16, 16, d - 16, d - 16], outline=STAMP, width=1)
    big, small = _font(34, bold=True), _font(11, bold=True)
    sd.text((d / 2, d / 2 - 6), label, font=big, fill=STAMP, anchor="mm")
    sd.text((d / 2, d / 2 + 22), "AUTHORISED", font=small, fill=STAMP, anchor="mm")
    seal = seal.rotate(-12, expand=True, resample=Image.Resampling.BICUBIC)
    img.paste(seal, (cx - seal.width // 2, cy - seal.height // 2), seal)


def _header(draw: ImageDraw.ImageDraw, prov: dict[str, Any], width: int) -> int:
    """Draw the provider letterhead band; return the y where the body should start."""
    accent = tuple(prov.get("accent", (31, 73, 125)))
    draw.rectangle([0, 0, width, 96], fill=accent)
    # logo tile
    draw.rounded_rectangle([28, 22, 80, 74], radius=10, fill=PAPER)
    initials = "".join(w[0] for w in prov["name"].split()[:2]).upper()
    draw.text((54, 48), initials, font=_font(24, bold=True), fill=accent, anchor="mm")
    draw.text((100, 26), prov["name"], font=_font(28, bold=True), fill=PAPER)
    draw.text((100, 62), prov.get("address", ""), font=_font(13), fill=(230, 235, 242))
    contact = "   ·   ".join(filter(None, [prov.get("gstin"), prov.get("phone")]))
    draw.text((width - 28, 70), contact, font=_font(12), fill=(230, 235, 242), anchor="rs")
    return 120


def _meta_block(draw: ImageDraw.ImageDraw, x0: int, y: int, width: int, title: str, rows: list[tuple[str, str]]) -> int:
    draw.text((x0, y), title, font=_font(22, bold=True), fill=INK)
    y += 38
    col = (width - 2 * x0) // 2
    for i, (k, v) in enumerate(rows):
        cx = x0 + (i % 2) * col
        cy = y + (i // 2) * 26
        draw.text((cx, cy), f"{k}: ", font=_font(13), fill=MUTE)
        draw.text((cx + _w(draw, f"{k}: ", _font(13)), cy), v, font=_font(13, bold=True), fill=INK)
    return y + ((len(rows) + 1) // 2) * 26 + 14


def _table(
    draw: ImageDraw.ImageDraw, x0: int, y: int, width: int, cols: list[tuple[str, int]], rows: list[list[str]]
) -> int:
    """A bordered, zebra-striped table. ``cols`` = [(heading, width_px), …]; last col right-aligned."""
    x1 = width - x0
    rh = 32
    # header
    draw.rectangle([x0, y, x1, y + rh], fill=(238, 241, 246))
    cx = x0
    for j, (head, cw) in enumerate(cols):
        right = j == len(cols) - 1
        tx = cx + cw - 12 if right else cx + 12
        draw.text((tx, y + rh / 2), head, font=_font(12, bold=True), fill=MUTE, anchor="rm" if right else "lm")
        cx += cw
    y += rh
    for i, row in enumerate(rows):
        if i % 2:
            draw.rectangle([x0, y, x1, y + rh], fill=ZEBRA)
        cx = x0
        for j, (val, (_, cw)) in enumerate(zip(row, cols, strict=False)):
            right = j == len(cols) - 1
            tx = cx + cw - 12 if right else cx + 12
            draw.text((tx, y + rh / 2), val, font=_font(13, bold=right), fill=INK, anchor="rm" if right else "lm")
            cx += cw
        y += rh
    draw.rectangle([x0, y - rh * (len(rows) + 1), x1, y], outline=LINE, width=1)
    return y


def render_invoice(spec: dict[str, Any], path: Path) -> None:
    W, H = 920, 1180
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = _header(d, spec["provider"], W)
    title = spec.get("title", "TAX INVOICE / RECEIPT")
    d.text((W / 2, y), title, font=_font(20, bold=True), fill=spec["provider"].get("accent", INK), anchor="mm")
    y += 30
    y = _meta_block(
        d, 28, y, W, "Bill details",
        [("Patient", spec["patient"]), ("Bill No", spec.get("doc_no", "INV-0001")),
         ("Date", spec["date"]), ("UHID", spec.get("uhid", "—"))],
    )
    cols = [("Description", 540), ("Qty", 100), ("Amount", 224)]
    rows = [[desc, str(qty), _inr(amt)] for desc, qty, amt in spec["items"]]
    y = _table(d, 28, y, W, cols, rows)
    # totals box
    y += 18
    d.rounded_rectangle([W - 320, y, W - 28, y + 50], radius=8, fill=(246, 249, 252), outline=LINE)
    d.text((W - 300, y + 25), "TOTAL PAYABLE", font=_font(13, bold=True), fill=MUTE, anchor="lm")
    d.text((W - 44, y + 25), _inr(spec["total"]), font=_font(20, bold=True), fill=INK, anchor="rm")
    # footer: stamp + signature
    fy = H - 150
    _stamp(img, 150, fy + 30)
    d.line([W - 280, fy + 60, W - 60, fy + 60], fill=INK, width=1)
    d.text((W - 170, fy + 70), "Authorised Signatory", font=_font(12), fill=MUTE, anchor="mm")
    d.text((28, H - 34), "This is a computer-generated invoice.", font=_font(11), fill=(160, 167, 178))
    img.save(path)


def render_prescription(spec: dict[str, Any], path: Path) -> None:
    W, H = 920, 1180
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = _header(d, spec["provider"], W)
    doc = spec.get("doctor", {})
    y = _meta_block(
        d, 28, y, W, "Prescription (Rx)",
        [("Doctor", doc.get("name", "—")), ("Reg. No", doc.get("reg", "—")),
         ("Patient", spec["patient"]), ("Date", spec["date"])],
    )
    if spec.get("diagnosis"):
        d.text((28, y), "Diagnosis: ", font=_font(13), fill=MUTE)
        d.text((28 + _w(d, "Diagnosis: ", _font(13)), y), spec["diagnosis"], font=_font(14, bold=True), fill=INK)
        y += 34
    # big Rx mark
    d.text((30, y + 4), "Rx", font=_font(46, bold=True), fill=spec["provider"].get("accent", INK))
    mx = 110
    for med in spec.get("medicines", []):
        d.ellipse([mx - 2, y + 24, mx + 4, y + 30], fill=INK)
        d.text((mx + 16, y + 16), med, font=_font(15), fill=INK)
        y += 38
    y += 30
    if spec.get("advice"):
        d.text((28, y), f"Advice: {spec['advice']}", font=_font(13), fill=MUTE)
    fy = H - 150
    d.line([W - 280, fy + 60, W - 60, fy + 60], fill=INK, width=1)
    d.text((W - 170, fy + 70), f"{doc.get('name', 'Physician')}", font=_font(12, bold=True), fill=INK, anchor="mm")
    d.text((W - 170, fy + 88), "Signature & Stamp", font=_font(11), fill=MUTE, anchor="mm")
    _stamp(img, 150, fy + 30, label="Rx")
    d.text((28, H - 34), "Valid for pharmacy dispensing.", font=_font(11), fill=(160, 167, 178))
    img.save(path)


def render_report(spec: dict[str, Any], path: Path) -> None:
    """Diagnostic / lab / dental report — a titled findings table."""
    W, H = 920, 1180
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = _header(d, spec["provider"], W)
    d.text((W / 2, y), spec.get("title", "DIAGNOSTIC REPORT"), font=_font(20, bold=True),
           fill=spec["provider"].get("accent", INK), anchor="mm")
    y += 30
    y = _meta_block(
        d, 28, y, W, "Report details",
        [("Patient", spec["patient"]), ("Ref. No", spec.get("doc_no", "LAB-0001")),
         ("Date", spec["date"]), ("Referred by", spec.get("doctor", {}).get("name", "—"))],
    )
    if spec.get("diagnosis"):
        d.text((28, y), "Impression: ", font=_font(13), fill=MUTE)
        d.text((28 + _w(d, "Impression: ", _font(13)), y), spec["diagnosis"], font=_font(14, bold=True), fill=INK)
        y += 34
    if spec.get("findings"):  # a results report (no prices)
        cols = [("Investigation", 420), ("Result", 240), ("Reference", 204)]
        rows = [[inv, res, ref] for inv, res, ref in spec["findings"]]
    else:  # a priced diagnostic bill
        cols = [("Investigation", 540), ("Qty", 100), ("Amount", 224)]
        rows = [[desc, str(qty), _inr(amt)] for desc, qty, amt in spec["items"]]
    y = _table(d, 28, y, W, cols, rows)
    fy = H - 150
    _stamp(img, 150, fy + 30, label="LAB")
    d.line([W - 280, fy + 60, W - 60, fy + 60], fill=INK, width=1)
    d.text((W - 170, fy + 70), "Pathologist", font=_font(12), fill=MUTE, anchor="mm")
    d.text((28, H - 34), "Electronically verified report.", font=_font(11), fill=(160, 167, 178))
    img.save(path)


_RENDERERS = {"invoice": render_invoice, "prescription": render_prescription, "report": render_report}


def _render_example(ex: dict[str, Any]) -> list[str]:
    folder = OUT / ex["id"]
    folder.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for doc in ex["docs"]:
        _RENDERERS[doc["kind"]](doc, folder / doc["file"])
        files.append(doc["file"])
    return files


# Which of the 12 documented test cases each example mirrors (shown as a badge in the UI).
_TC = {
    "approved_consultation": "TC004",
    "approved_network": "TC010",
    "approved_dental_partial": "TC006",
    "rejected_waiting_diabetes": "TC005",
    "rejected_excluded_bariatric": "TC012",
    "rejected_per_claim_limit": "TC008",
    "rejected_mri_no_preauth": "TC007",
    "review_same_day": "TC009",
}


def main() -> None:
    from eval.sample_specs import EXAMPLES  # the curated catalogue (kept separate for clarity)

    if OUT.exists():
        import shutil

        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for ex in EXAMPLES:
        files = _render_example(ex)
        manifest.append(
            {
                "id": ex["id"],
                "bucket": ex["bucket"],
                "label": ex["label"],
                "description": ex["description"],
                "form": ex["form"],
                "files": [f"/samples/{ex['id']}/{f}" for f in files],
                **({"tc": _TC[ex["id"]]} if ex["id"] in _TC else {}),
                **({"seed": ex["seed"]} if ex.get("seed") else {}),
            }
        )
        print(f"  ✓ {ex['bucket']:8} {ex['id']:28} ({len(files)} doc(s))")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest → {OUT / 'manifest.json'} ({len(manifest)} examples)")


if __name__ == "__main__":
    main()
