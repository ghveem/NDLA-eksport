"""
fiks-qr.py — set inn QR-kodar i eksisterande eksport-PDF-ar
Finn embed-boksane (H5P, video o.l.) og set inn QR-kode som
peikar til ndla.no-artikkelsida.

Bruk:
  python fiks-qr.py               # finn siste eksportmappe automatisk
  python fiks-qr.py <mappe>       # t.d. kinesisk-1-26-09-22
"""

import io
import re
import sys
from pathlib import Path

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
)

QR_SIZE_PT = 110   # punktar (≈ 39 mm) på sida


# ── Hjelpefunksjonar ──────────────────────────────────────────────────────────

def make_qr_png(url: str) -> bytes:
    qr  = segno.make(url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=4, border=2)
    return buf.getvalue()


def is_embed_link(uri: str) -> bool:
    return any(d in uri for d in EMBED_DOMAINS)


def find_article_url(links: list) -> str | None:
    """Finn ndla.no-artikkels-URL frå 'Kjelde:'-lenka (legg vekk Matomo-params)."""
    for link in links:
        uri = link.get("uri", "")
        if uri.startswith("https://ndla.no") and "article-iframe" not in uri:
            return uri.split("?")[0]
    return None


def fix_page(page: pymupdf.Page) -> int:
    """Set inn QR-kodar på éi side. Returnerer antal sette inn."""
    links = page.get_links()
    if not links:
        return 0

    ndla_url = find_article_url(links)
    if not ndla_url:
        return 0

    embed_links = [lk for lk in links if is_embed_link(lk.get("uri", ""))]
    if not embed_links:
        return 0

    qr_png = make_qr_png(ndla_url)
    inserted = 0

    for link in embed_links:
        link_rect = pymupdf.Rect(link["from"])

        # Plasser QR-bilete like over embed-lenka
        qr_rect = pymupdf.Rect(
            link_rect.x0,
            link_rect.y0 - QR_SIZE_PT - 6,
            link_rect.x0 + QR_SIZE_PT,
            link_rect.y0 - 6,
        )

        # Sikre at me ikkje går utanfor sida
        if qr_rect.y0 < page.rect.y0 + 10:
            shift = (page.rect.y0 + 10) - qr_rect.y0
            qr_rect = pymupdf.Rect(
                qr_rect.x0, qr_rect.y0 + shift,
                qr_rect.x1, qr_rect.y1 + shift,
            )

        page.insert_image(qr_rect, stream=qr_png)
        inserted += 1

    return inserted


def fix_pdf(pdf_path: Path) -> int:
    """Fiksar alle sider i ein PDF. Returnerer total antal QR sette inn."""
    doc   = pymupdf.open(str(pdf_path))
    total = 0

    for page_num in range(len(doc)):
        n = fix_page(doc[page_num])
        total += n

    if total > 0:
        doc.save(str(pdf_path), incremental=True,
                 encryption=pymupdf.PDF_ENCRYPT_KEEP)
        print(f"  ✅ {pdf_path.name}: {total} QR-kodar sett inn")
    else:
        print(f"  –  {pdf_path.name}: ingen embed-boks funnen")

    doc.close()
    return total


def pick_folder() -> Path:
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
        if not folder.is_dir():
            print(f"❌  Mappa {folder} finst ikkje.")
            sys.exit(1)
        return folder

    # Finn nyaste eksportmappe automatisk
    candidates = sorted(Path(".").glob("*-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]"))
    if not candidates:
        print("❌  Ingen eksportmappe funnen i gjeldande mappe.")
        sys.exit(1)
    return candidates[-1]


def remerge(folder: Path):
    """Slår saman individuelle sider til ny hovud-PDF."""
    sider_dir = folder / "sider"
    merged    = folder / f"{folder.name}.pdf"

    print(f"\nSlår saman på nytt → {merged.name} …")
    merger = pymupdf.open()
    for f in sorted(sider_dir.glob("*.pdf")):
        merger.insert_pdf(pymupdf.open(str(f)))
    merger.save(str(merged))
    merger.close()
    print(f"✅ Ny samla PDF: {merged}")


# ── Hovudprogram ──────────────────────────────────────────────────────────────

def main():
    folder    = pick_folder()
    sider_dir = folder / "sider"

    if not sider_dir.is_dir():
        print(f"❌  Ingen sider/-mappe i {folder}. Er dette ei eksportmappe?")
        sys.exit(1)

    pdfs = sorted(sider_dir.glob("*.pdf"))
    print(f"\nEksportmappe: {folder}/")
    print(f"Fiksar QR-kodar i {len(pdfs)} sider …\n")

    total = sum(fix_pdf(p) for p in pdfs if p.stem != "0000_toc")

    if total > 0:
        remerge(folder)
        print(f"\n🎉 Ferdig — {total} QR-kodar totalt.")
    else:
        print("\nℹ️  Ingen embed-boksane vart funne. Er PDFen allereie oppdatert?")


if __name__ == "__main__":
    main()
