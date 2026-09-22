"""
NDLA PDF-eksport — proof of concept
Genererer ein samla PDF av alle artiklar i eit NDLA-fag,
basert på ei sitemap-fil med NDLA-adresser.

Bruk:
  pip install -r requirements.txt
  playwright install chromium
  python eksport.py
"""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright
import pypdf

# ── Konfigurasjon ─────────────────────────────────────────────────────────────

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
    a[href] { color: #004785; text-decoration: underline; }
"""

# ── Hjelpefunksjonar ──────────────────────────────────────────────────────────

def derive_slug(sitemap_file: str) -> str:
    """kinesisk-1 frå sitemap-f-kinesisk-1-4d34e9487d52.txt"""
    stem = Path(sitemap_file).stem
    stem = stem.removeprefix("sitemap-f-")
    stem = re.sub(r"-[0-9a-f]{8,}$", "", stem)
    return stem


def pick_sitemap() -> Path:
    """Finn sitemap-filer i gjeldande mappe og la brukaren velje."""
    candidates = sorted(Path(".").glob("sitemap-f-*.txt"))
    if not candidates:
        print("❌  Ingen sitemap-fil funnen i mappa.")
        print("    Last ned ei frå https://ndla.no/sitemap.xml og legg ho her.")
        sys.exit(1)

    if len(candidates) == 1:
        f = candidates[0]
        slug = derive_slug(str(f))
        svar = input(f"\nFann: {f.name}  ({slug})\nEksportere dette faget? [J/n] ").strip().lower()
        if svar in ("n", "nei"):
            print("Avbryt.")
            sys.exit(0)
        return f

    # Fleire filer — vis meny
    print("\nFann fleire sitemap-filer:")
    for i, f in enumerate(candidates, 1):
        print(f"  {i}. {f.name}  ({derive_slug(str(f))})")
    val = input(f"\nVel fag [1–{len(candidates)}]: ").strip()
    try:
        return candidates[int(val) - 1]
    except (ValueError, IndexError):
        print("Ugyldig val. Avbryt.")
        sys.exit(1)


async def get_iframe_info(client: httpx.AsyncClient, article_url: str):
    """Hent iframeSrc og tittel frå oEmbed-endepunktet."""
    try:
        resp = await client.get(
            f"https://ndla.no/oembed?url={article_url}", timeout=15
        )
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
        safe_url = original_url.replace("'", "%27")
        await page.evaluate(f"""() => {{
            const footer = document.createElement('div');
            footer.style.cssText = 'margin-top:24px;padding-top:8px;border-top:1px solid #ccc;'
                                 + 'font-size:9pt;font-family:sans-serif;color:#444;'
                                 + 'page-break-inside:avoid;';
            footer.innerHTML = 'Kjelde: <a href="{safe_url}" '
                             + 'style="color:#004785;text-decoration:underline;">'
                             + '{safe_url}</a>';
            document.body.appendChild(footer);
        }}""")

    await page.pdf(
        path=str(out_path),
        format="A4",
        tagged=True,
        print_background=False,
        margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"},
    )


def build_toc_html(toc: list, subject: str, generated_at: str, pdf_name: str = "") -> str:
    items  = "\n".join(f"<li>{t}</li>" for t, _, _, _ in toc)
    subj   = f"PDF-eksport-av-fag: {pdf_name}" if pdf_name else "PDF-eksport-av-fag"
    mailto = f"hjelp@ndla.no?subject={subj}"
    return f"""<!DOCTYPE html>
<html lang="nb"><head><meta charset="utf-8"><style>
  body{{font-family:sans-serif;padding:30px;}}
  h1{{font-size:18pt;margin-bottom:4px;}}
  .meta{{color:#555;font-size:10pt;margin-bottom:16px;}}
  .disclaimer{{background:#f5f5f5;border-left:3px solid #004785;
    padding:10px 14px;font-size:10pt;color:#333;margin-bottom:20px;line-height:1.5;}}
  a{{color:#004785;}} ol{{margin-top:0;}} li{{padding:4px 0;font-size:11pt;}}
  @page{{size:A4;margin:20mm;}}
</style></head><body>
  <h1>{subject}</h1>
  <p class="meta">Generert: {generated_at} &nbsp;·&nbsp; {len(toc)} artiklar</p>
  <div class="disclaimer">
    <strong>Merk:</strong> Artiklane på <a href="https://ndla.no">ndla.no</a> kan ha
    blitt oppdaterte etter at denne PDF-en vart generert. Sjekk gjerne den originale
    artikkelen viss du oppdagar feil. Vil du melde frå om ein feil i PDFen, send
    e-post til <a href="mailto:{mailto}">{mailto.split('?')[0]}</a>.
  </div>
  <ol>{items}</ol>
</body></html>"""


# ── Hovudprogram ──────────────────────────────────────────────────────────────

async def main():
    sitemap_path = pick_sitemap()
    slug         = derive_slug(str(sitemap_path))
    date_str     = datetime.now().strftime("%y-%m-%d")
    folder       = Path(f"{slug}-{date_str}")
    out_dir      = folder / "sider"
    output_pdf   = folder / f"{slug}-{date_str}.pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    print(f"\nFag: {slug}  →  utmappe: {folder}/")

    all_urls = [
        line.strip()
        for line in sitemap_path.read_text(encoding="utf-8").splitlines()
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
                print(f"  ⚠️  {i+1:3d}/{len(urls)}: ingen iframeSrc — hoppar over ({url})")

    print(f"\nLagar PDF-ar for {len(toc)} artiklar …")
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page    = await browser.new_page()

        # Innhaldsliste
        subject  = slug.replace("-", " ").title()
        toc_html = build_toc_html(toc, subject, generated_at, output_pdf.name)
        await page.set_content(toc_html, wait_until="load")
        await page.pdf(path=str(out_dir / "0000_toc.pdf"), format="A4", tagged=True,
                       margin={"top":"20mm","bottom":"20mm","left":"20mm","right":"20mm"})
        print("  TOC: ferdig")

        # Artiklar med retry
        for i, (title, fname, iframe_url, original_url) in enumerate(toc):
            out_path = out_dir / fname
            print(f"  {i+1:3d}/{len(toc)}: {title}")
            last_exc = None
            for attempt in range(3):
                try:
                    await render_to_pdf(page, iframe_url, out_path,
                                        original_url, title)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        print(f"       ↩️  Forsøk {attempt + 2}/3 ({exc})")
                        await asyncio.sleep(2)
            if last_exc is not None:
                print(f"       ❌ Feila etter 3 forsøk: {last_exc}  ({original_url})")
                errors.append((title, original_url, str(last_exc)))

        await browser.close()

    # Slå saman
    print(f"\nSlår saman til {output_pdf} …")
    merger = pypdf.PdfWriter()
    for f in sorted(out_dir.glob("*.pdf")):
        merger.append(str(f))
    merger.write(str(output_pdf))
    merger.close()

    print(f"\n✅ Ferdig: {output_pdf}  ({len(toc) - len(errors)} artiklar + TOC)")
    if errors:
        print(f"\n⚠️  {len(errors)} artiklar feila:")
        for title, url, msg in errors:
            print(f"  - {title}\n    {url}\n    {msg}")


if __name__ == "__main__":
    asyncio.run(main())
