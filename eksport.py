"""
NDLA PDF-eksport — proof of concept
Genererer ein samla PDF av alle artiklar i eit fag,
basert på ei sitemap-fil med NDLA-adresser.

Bruk:
  pip install -r requirements.txt
  playwright install chromium
  python eksport.py
"""

import asyncio
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
import pypdf

# ── Konfigurasjon ─────────────────────────────────────────────────────────────

SITEMAP_FILE = "sitemap-f-matematikk-2p-36bbf8f78d78.txt"
OUTPUT_PDF    = "matematikk-2p.pdf"
OUT_DIR       = Path("pdf_out")

OEMBED_BASE   = "https://ndla.no/oembed?url="

# /f/ er sjølve faget – hoppar over
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
    /* Gjer alle lenker synlege i utskrift */
    a[href] {
        color: #004785;
        text-decoration: underline;
    }
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


async def render_to_pdf(page, iframe_url: str, out_path: Path,
                        original_url: str = "", title: str = ""):
    """Opne article-iframe-URL i Playwright og lag PDF."""
    await page.goto(iframe_url, wait_until="networkidle", timeout=60_000)
    await page.add_style_tag(content=PRINT_CSS)

    if original_url:
        safe_url   = original_url.replace("'", "%27")
        safe_title = title.replace("'", "\\'").replace("`", "\\`")
        await page.evaluate(f"""() => {{
            // Tittel-header med klikkbar lenke til ndla.no
            const header = document.createElement('div');
            header.style.cssText = 'margin-bottom:12px; font-size:10pt; font-family:sans-serif;';
            header.innerHTML = '<a href="{safe_url}" style="color:#004785;text-decoration:underline;">'
                             + '↗ Les oppdatert versjon på ndla.no: {safe_title}'
                             + '</a>';
            document.body.insertBefore(header, document.body.firstChild);

            // Footer med synleg URL
            const footer = document.createElement('div');
            footer.style.cssText = 'margin-top:24px; padding-top:8px; border-top:1px solid #ccc;'
                                 + 'font-size:9pt; font-family:sans-serif; color:#444;'
                                 + 'page-break-inside:avoid;';
            footer.innerHTML = 'Kjelde: <a href="{safe_url}" style="color:#004785;text-decoration:underline;">'
                             + '{safe_url}</a>';
            document.body.appendChild(footer);
        }}""")

    await page.pdf(
        path=str(out_path),
        format="A4",
        print_background=False,
        margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"},
    )


def build_toc_html(toc: list, subject: str, generated_at: str) -> str:
    """Lag ein enkel innhaldsliste som HTML."""
    items = "\n".join(f"<li>{title}</li>" for title, _, _, _ in toc)
    mailto = "hjelp@ndla.no?subject=PDF-eksport-av-fag"
    return f"""<!DOCTYPE html>
<html lang="nb">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: sans-serif; padding: 30px; }}
    h1   {{ font-size: 18pt; margin-bottom: 4px; }}
    .meta {{ color: #555; font-size: 10pt; margin-bottom: 16px; }}
    .disclaimer {{
        background: #f5f5f5; border-left: 3px solid #004785;
        padding: 10px 14px; font-size: 10pt; color: #333;
        margin-bottom: 20px; line-height: 1.5;
    }}
    a {{ color: #004785; }}
    ol {{ margin-top: 0; }}
    li {{ padding: 4px 0; font-size: 11pt; }}
    @page {{ size: A4; margin: 20mm; }}
  </style>
</head>
<body>
  <h1>{subject}</h1>
  <p class="meta">Generert: {generated_at} &nbsp;·&nbsp; {len(toc)} artiklar</p>
  <div class="disclaimer">
    <strong>Merk:</strong> Artiklane på <a href="https://ndla.no">ndla.no</a> kan ha
    blitt oppdaterte etter at denne PDF-en vart generert. Sjekk gjerne den originale
    artikkelen viss du oppdagar feil. Vil du melde frå om ein feil i PDFen, send
    e-post til <a href="mailto:{mailto}">{mailto.split('?')[0]}</a>.
  </div>
  <ol>
{items}
  </ol>
</body>
</html>"""


# ── Hovudprogram ──────────────────────────────────────────────────────────────

async def main():
    OUT_DIR.mkdir(exist_ok=True)
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    all_urls = [
        line.strip()
        for line in Path(SITEMAP_FILE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    urls = [u for u in all_urls if any(t in u for t in INCLUDE_TYPES)]
    print(f"Sitemap: {len(all_urls)} URL-ar totalt, {len(urls)} artiklar (/e/ + /r/)")

    # toc: (display_title, filnamn, iframe_url, original_ndla_url)
    toc = []
    print("\nHentar titlar via oEmbed …")
    async with httpx.AsyncClient() as client:
        for i, url in enumerate(urls):
            iframe_url, title = await get_iframe_info(client, url)
            if iframe_url:
                display_title = f"Emne: {title}" if "/e/" in url else title
                toc.append((display_title, f"{i:04d}.pdf", iframe_url, url))
                print(f"  {i+1:3d}/{len(urls)}: {display_title}")
            else:
                print(f"  {i+1:3d}/{len(urls)}: HOPPAR OVER (ingen iframeSrc)")

    print(f"\nLagar PDF-ar for {len(toc)} artiklar …")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page    = await browser.new_page()

        # Innhaldsliste
        subject  = (Path(SITEMAP_FILE).stem
                    .replace("sitemap-f-", "")
                    .replace("-", " ")
                    .title())
        toc_html = build_toc_html(toc, subject, generated_at)
        await page.set_content(toc_html, wait_until="load")
        await page.pdf(path=str(OUT_DIR / "0000_toc.pdf"), format="A4",
                       margin={"top":"20mm","bottom":"20mm","left":"20mm","right":"20mm"})
        print("  TOC: ferdig")

        # Artiklar
        for i, (title, fname, iframe_url, original_url) in enumerate(toc):
            print(f"  {i+1:3d}/{len(toc)}: {title}")
            try:
                await render_to_pdf(page, iframe_url, OUT_DIR / fname,
                                    original_url, title)
            except Exception as exc:
                print(f"       ⚠️  Feil: {exc}")

        await browser.close()

    print(f"\nSlår saman til {OUTPUT_PDF} …")
    merger = pypdf.PdfWriter()
    for f in sorted(OUT_DIR.glob("*.pdf")):
        merger.append(str(f))
    merger.write(OUTPUT_PDF)
    merger.close()
    print(f"✅ Ferdig: {OUTPUT_PDF}  ({len(toc)} artiklar + TOC)")


if __name__ == "__main__":
    asyncio.run(main())
