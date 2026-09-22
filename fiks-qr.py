"""
fiks-qr.py — set inn / rydde QR-kodar i eksisterande eksport-PDF-ar

Bruk:
  python fiks-qr.py               # finn siste eksportmappe automatisk
  python fiks-qr.py <mappe>       # t.d. kinesisk-1-26-09-22
  python fiks-qr.py --rens        # fjern dupliserte QR-kodar
  python fiks-qr.py --debug       # list alle lenker (maks 20 sider)
"""

import io
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pymupdf
import segno

# ── Konfigurasjon ─────────────────────────────────────────────────────────────

EMBED_DOMAINS = (
    "h5p.ndla.no",
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "brightcove.com",
    "bcove.video",
    "players.brightcove.net",
    "boltdns.net",
)

QR_SIZE_PT = 110   # punktar (≈ 39 mm) på sida
QR_MIN_PT  = 80    # minste kvadratbilete som reknast som QR
QR_MAX_PT  = 160   # største kvadratbilete som reknast som QR


# ── Hjelpefunksjonar ──────────────────────────────────────────────────────────

def make_qr_png(url: str) -> bytes:
    qr  = segno.make(url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=4, border=2)
    return buf.getvalue()


def matomo_url(url: str, pdf_name: str) -> str:
    sep = "&" if "?" in url else "?"
    return url + sep + "mtm_source=pdf-eksport&mtm_medium=" + quote(pdf_name, safe="")


def is_embed_link(uri: str) -> bool:
    return any(d in uri for d in EMBED_DOMAINS)


def find_article_url(page: pymupdf.Page) -> str | None:
    """Finn ndla.no-artikkels-URL frå lenker eller synleg tekst."""
    for link in page.get_links():
        uri = link.get("uri", "")
        if uri.startswith("https://ndla.no") and "article-iframe" not in uri:
            return uri.split("?")[0]
    # Fallback: synleg tekst
    m = re.search(r'https://ndla\.no/[^\s"<>]+', page.get_text())
    if m:
        url = m.group(0).rstrip(".,)")
        if "article-iframe" not in url:
            return url.split("?")[0]
    return None


def is_qr_candidate(rect: pymupdf.Rect) -> bool:
    """Kvadratisk bilete i rimeleg QR-storleik?"""
    w, h = rect.width, rect.height
    if w < QR_MIN_PT or w > QR_MAX_PT:
        return False
    aspect = w / h if h > 0 else 0
    return 0.75 < aspect < 1.35


def has_image_at(page: pymupdf.Page, target: pymupdf.Rect) -> bool:
    """Ligg det allereie eit bilete nær target-rekt?"""
    for img in page.get_image_info():
        r = pymupdf.Rect(img["bbox"])
        if not is_qr_candidate(r):
            continue
        inter = r & target
        if inter.is_valid and inter.get_area() > 0.5 * target.get_area():
            return True
    return False


# ── Rens: fjern dupliserte QR-kodar ──────────────────────────────────────────

def rens_page(page: pymupdf.Page) -> int:
    """Rediger vekk dupliserte kvadratbilete (QR-kodar). Returnerer antal fjerna."""
    images = [
        pymupdf.Rect(img["bbox"])
        for img in page.get_image_info()
        if is_qr_candidate(pymupdf.Rect(img["bbox"]))
    ]
    if len(images) <= 1:
        return 0

    # Kluster bilde som overlapper meir enn 60 %
    kept    = []
    removed = 0
    for rect in images:
        dup = False
        for seen in kept:
            inter = rect & seen
            if inter.is_valid and inter.get_area() > 0.6 * rect.get_area():
                dup = True
                break
        if dup:
            # Dekk over med kvit boks
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
            removed += 1
        else:
            kept.append(rect)

    return removed


def rens_pdf(pdf_path: Path) -> int:
    doc   = pymupdf.open(str(pdf_path))
    total = 0
    for page_num in range(len(doc)):
        total += rens_page(doc[page_num])
    if total > 0:
        doc.save(str(pdf_path), incremental=True,
                 encryption=pymupdf.PDF_ENCRYPT_KEEP)
        print(f"  🧹 {pdf_path.name}: {total} duplikat(ar) fjerna")
    else:
        print(f"  –  {pdf_path.name}: ingen duplikat")
    doc.close()
    return total


# ── Sett inn QR-kodar ─────────────────────────────────────────────────────────

def fix_page(page: pymupdf.Page, pdf_name: str = "", article_url: str | None = None) -> int:
    links = page.get_links()
    embed_links = [lk for lk in links if is_embed_link(lk.get("uri", ""))]
    if not embed_links:
        return 0

    ndla_url = article_url or find_article_url(page)
    if not ndla_url:
        return 0

    qr_url = matomo_url(ndla_url, pdf_name) if pdf_name else ndla_url
    qr_png = make_qr_png(qr_url)
    inserted = 0

    for link in embed_links:
        link_rect = pymupdf.Rect(link["from"])
        qr_rect   = pymupdf.Rect(
            link_rect.x0,
            link_rect.y0 - QR_SIZE_PT - 6,
            link_rect.x0 + QR_SIZE_PT,
            link_rect.y0 - 6,
        )

        # Korriger viss me går utanfor sida
        if qr_rect.y0 < page.rect.y0 + 10:
            shift   = (page.rect.y0 + 10) - qr_rect.y0
            qr_rect = pymupdf.Rect(
                qr_rect.x0, qr_rect.y0 + shift,
                qr_rect.x1, qr_rect.y1 + shift,
            )

        # Ikkje set inn om det allereie ligg eit bilete der
        if has_image_at(page, qr_rect):
            continue

        page.insert_image(qr_rect, stream=qr_png)
        inserted += 1

    return inserted


def fix_pdf(pdf_path: Path, pdf_name: str = "") -> int:
    doc = pymupdf.open(str(pdf_path))
    # Skann alle sider fyrst for å finne artikkel-URL
    # (Kjelde:-lenka kan liggje på siste side, embed på fyrste)
    article_url = None
    for pn in range(len(doc)):
        article_url = find_article_url(doc[pn])
        if article_url:
            break
    total = 0
    for page_num in range(len(doc)):
        total += fix_page(doc[page_num], pdf_name, article_url)
    if total > 0:
        doc.save(str(pdf_path), incremental=True,
                 encryption=pymupdf.PDF_ENCRYPT_KEEP)
        print(f"  ✅ {pdf_path.name}: {total} QR-kodar sett inn")
    else:
        print(f"  –  {pdf_path.name}: ingen embed-boks funnen")
    doc.close()
    return total


# ── Sameining og navigasjon ───────────────────────────────────────────────────

def pick_folder() -> Path:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        folder = Path(args[0])
        if not folder.is_dir():
            print(f"❌  Mappa {folder} finst ikkje.")
            sys.exit(1)
        return folder
    candidates = sorted(Path(".").glob("*-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]"))
    if not candidates:
        print("❌  Ingen eksportmappe funnen.")
        sys.exit(1)
    return candidates[-1]


def remerge(folder: Path):
    sider_dir = folder / "sider"
    merged    = folder / f"{folder.name}.pdf"
    print(f"\nSlår saman på nytt → {merged.name} …")
    merger = pymupdf.open()
    for f in sorted(sider_dir.glob("*.pdf")):
        merger.insert_pdf(pymupdf.open(str(f)))
    # Skriv til bytes fyrst for å unngå slett+opprette (ikkje tillate i delt mappe)
    data = merger.tobytes()
    merger.close()
    merged.write_bytes(data)
    print(f"✅ Ny samla PDF: {merged}")


def debug_links(folder: Path):
    for p in sorted((folder / "sider").glob("*.pdf"))[:20]:
        doc = pymupdf.open(str(p))
        for i, page in enumerate(doc):
            lks = page.get_links()
            if lks:
                print(f"\nSide {i}: {p.name}")
                for lk in lks:
                    print(f"  {lk.get('uri', '')}")
        doc.close()



# ── Framsideboksar ────────────────────────────────────────────────────────────

def add_cover_boxes(toc_path: Path) -> bool:
    """Legg til disclaimer- og QR-forklaringsboks nedst på framsida."""
    doc  = pymupdf.open(str(toc_path))
    page = doc[0]
    pw   = page.rect.width
    ph   = page.rect.height

    BLUE  = (0, 71/255, 133/255)          # #004785
    LBLUE = (230/255, 240/255, 250/255)   # lys blå
    AMBER = (253/255, 248/255, 236/255)   # lys amber
    DARK  = (0.1, 0.1, 0.1)

    M  = 40
    BW = pw - 2 * M

    B2_H = 76
    B1_H = 52
    GAP  = 10
    b2_y = ph - M - B2_H
    b1_y = b2_y - GAP - B1_H

    # Boks 1: Disclaimer
    r1 = pymupdf.Rect(M, b1_y, M + BW, b1_y + B1_H)
    page.draw_rect(r1, color=BLUE, fill=LBLUE, width=1.2)
    n1 = page.insert_textbox(
        pymupdf.Rect(r1.x0 + 8, r1.y0 + 8, r1.x1 - 8, r1.y1 - 8),
        "Dette er ein uoffisiell PDF-eksport frå ndla.no. "
        "Innhaldet kan vere utdatert. Sjå ndla.no for siste versjon.",
        fontname="helv", fontsize=9, color=DARK,
    )

    # Boks 2: QR-forklaring
    r2 = pymupdf.Rect(M, b2_y, M + BW, b2_y + B2_H)
    page.draw_rect(r2, color=BLUE, fill=AMBER, width=1.2)
    n2 = page.insert_textbox(
        pymupdf.Rect(r2.x0 + 8, r2.y0 + 8, r2.x1 - 8, r2.y1 - 8),
        "Videoar, simuleringar og interaktivt innhald — "
        "Denne PDF-en inneheld artiklar med innebygde videoar, simuleringar og andre "
        "interaktive element. Slikt innhald kan ikkje visast i ein PDF, og er difor "
        "erstatta med ein QR-kode. Skann QR-koden med mobilen, "
        "så kjem du direkte til artikkelen på ndla.no.",
        fontname="helv", fontsize=9, color=DARK,
    )

    if n1 < 0 or n2 < 0:
        print("  ⚠️  Tekst gjekk utanfor boks — prøv mindre skrift")

    doc.save(str(toc_path), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    doc.close()
    return True

# ── Hovudprogram ──────────────────────────────────────────────────────────────

def main():
    folder    = pick_folder()
    sider_dir = folder / "sider"
    if not sider_dir.is_dir():
        print(f"❌  Ingen sider/-mappe i {folder}.")
        sys.exit(1)

    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--debug" in flags:
        debug_links(folder)
        return

    pdfs = sorted(sider_dir.glob("*.pdf"))

    if "--rens" in flags:
        print(f"\nEksportmappe: {folder}/")
        print(f"Ryddar duplikat-QR i {len(pdfs)} sider …\n")
        total = sum(rens_pdf(p) for p in pdfs if p.stem != "0000_toc")
        if total > 0:
            remerge(folder)
            print(f"\n🎉 Ferdig — {total} duplikat(ar) fjerna.")
        else:
            print("\nℹ️  Ingen duplikat funne.")
        return

    if "--infoboks" in flags:
        toc_path = sider_dir / "0000_toc.pdf"
        if not toc_path.exists():
            print("\u274c  0000_toc.pdf finst ikkje i sider/.")
            sys.exit(1)
        print(f"\nLegg til infoboksar på framsida …")
        add_cover_boxes(toc_path)
        print("  \u2705 Infoboksar lagt til")
        remerge(folder)
        print("\n\U0001f389 Ferdig.")
        return

    pdf_name = folder.name + ".pdf"
    print(f"\nEksportmappe: {folder}/")
    print(f"Set inn QR-kodar i {len(pdfs)} sider (kampanjesporing: {pdf_name}) …\n")
    total = sum(fix_pdf(p, pdf_name) for p in pdfs if p.stem != "0000_toc")
    if total > 0:
        remerge(folder)
        print(f"\n🎉 Ferdig — {total} QR-kodar totalt.")
    else:
        print("\nℹ️  Ingen embed-boksane vart funne.")
        print("    Køyr med --debug for å sjå kva lenker som finst.")


if __name__ == "__main__":
    main()
