"""
NDLA PDF-eksport — proof of concept
Genererer ein samla PDF av alle artiklar i eit fag,
basert på ei sitemap-fil med NDLA-adresser.

Inkluderer:
  - /e/  emneartiklar  (kapittel-/emneoversikter)
  - /r/  ressursartiklar (fagartiklar)

Bruk:
  pip install -r requirements.txt
  playwright install chromium
  python eksport.py
"""

import asyncio
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
import pypdf

# ── Konfigurasjon ─────────────────────────────────────────────────────────────

SITEMAP_FILE = "sitemap-f-matematikk-2p-36bbf8f78d78.txt"
OUTPUT_PDF    = "matematikk-2p.pdf"
OUT_DIR       = Path("pdf_out")

OEMBED_BASE   = "https://ndla.no/oembed?url="

# Artikkeltypar som skal takast med (/f/ er sjølve faget – hoppar over)
INCLUDE_TYPES = ("/e/", "/r/")

PRINT_CSS = """
    body {
        font-size: 11pt;
        font-family: Georgia, serif;
        line-height: 1.5;
        color: #111;
    }
    @page { size: A4; margin: 20mm; }
    img { max-width: 100%; }
    figure, .c-figure { page-break-inside: avoid; }
    h1, h2, h3 { page-break-after: avoid; }
    pre, code { font-size: 9pt; }
    nav, .c-breadcrumb, footer { display: none !important; }
"""

# ── Hjelpefunksjonar ──────────────────────────────────────────────────────────

async def get_iframe_info(client: httpx.AsyncClient, article_url: str):
    """Hent iframeSrc og tittel frå oEmbed-endepunktet."""
    try:
        resp = await client.get(f"{OEMBED_BASE}{article_url}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("iframeSrc"), data.get("title", article_url)
    except Exception as exc:
        print(f"  ⚠️  oEmbed feil for {article_url}: {exc}")
        return None, article_url


async def render_to_pdf(page, iframe_url: str, out_path: Path):
    """Opne article-iframe-URL i Playwright og lag PDF."""
    await page.goto(iframe_url, wait_until="networkidle", timeout=60_000)
    await page.add_style_tag(content=PRINT_CSS)
    await page.pdf(
        path=str(out_path),
        format="A4",
        print_background=False,
        margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"},
    )


def build_toc_html(toc: list, subject: str) -> str:
    """Lag ein enkel innhaldsliste som HTML."""
    items = "\n".join(f"<li>{title}</li>" for title, _, _ in toc)
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: sans-serif; padding: 30px; }}
    h1   {{ font-size: 18pt; margin-bottom: 4px; }}
    p    {{ color: #555; margin-top: 0; }}
    ol   {{ margin-top: 16px; }}
    li   {{ padding: 4px 0; font-size: 11pt; }}
    @page {{ size: A4; margin: 20mm; }}
  </style>
</head>
<body>
  <h1>{subject}</h1>
  <p>Innhaldsliste — {len(toc)} artiklar</p>
  <ol>
{items}
  </ol>
</body>
</html>"""


# ── Hovudprogram ──────────────────────────────────────────────────────────────

async def main():
    OUT_DIR.mkdir(exist_ok=True)

    # Les sitemap og filtrer relevante URL-ar
    all_urls = [
        line.strip()
        for line in Path(SITEMAP_FILE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    urls = [u for u in all_urls if any(t in u for t in INCLUDE_TYPES)]
    print(f"Sitemap: {len(all_urls)} URL-ar totalt, {len(urls)} artiklar (/e/ + /r/)")

    # Hent iframeSrc og tittel for alle artiklar via oEmbed
    toc = []  # list of (tittel, filnamn, iframe_url)
    print("\nHentar titlar via oEmbed …")
    async with httpx.AsyncClient() as client:
        for i, url in enumerate(urls):
            iframe_url, title = await get_iframe_info(client, url)
            if iframe_url:
                fname = f"{i:04d}.pdf"
                toc.append((title, fname, iframe_url))
                print(f"  {i+1:3d}/{len(urls)}: {title}")
            else:
                print(f"  {i+1:3d}/{len(urls)}: HOPPAR OVER (ingen iframeSrc)")

    print(f"\nLagar PDF-ar for {len(toc)} artiklar …")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page    = await browser.new_page()

        # Innhaldsliste (side 0)
        subject = (Path(SITEMAP_FILE).stem
                   .replace("sitemap-f-", "")
                   .replace("-", " ")
                   .title())
        toc_html = build_toc_html(toc, subject)
        await page.set_content(toc_html, wait_until="load")
        toc_pdf = OUT_DIR / "0000_toc.pdf"
        await page.pdf(path=str(toc_pdf), format="A4",
                       margin={"top":"20mm","bottom":"20mm","left":"20mm","right":"20mm"})
        print("  TOC: ferdig")

        # Artiklar
        for i, (title, fname, iframe_url) in enumerate(toc):
            out_path = OUT_DIR / fname
            print(f"  {i+1:3d}/{len(toc)}: {title}")
            try:
                await render_to_pdf(page, iframe_url, out_path)
            except Exception as exc:
                print(f"       ⚠️  Feil: {exc}")

        await browser.close()

    # Slå saman alle PDF-ar
    print(f"\nSlår saman til {OUTPUT_PDF} …")
    merger = pypdf.PdfWriter()
    for f in sorted(OUT_DIR.glob("*.pdf")):
        merger.append(str(f))
    merger.write(OUTPUT_PDF)
    merger.close()
    print(f"✅ Ferdig: {OUTPUT_PDF}  ({len(toc)} artiklar + TOC)")


if __name__ == "__main__":
    asyncio.run(main())
