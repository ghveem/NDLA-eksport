"""
fiks-qr.py — set inn / rydde QR-kodar i eksisterande eksport-PDF-ar

Bruk:
  python fiks-qr.py               # finn siste eksportmappe automatisk
  python fiks-qr.py <mappe>       # t.d. kinesisk-1-26-09-22
  python fiks-qr.py --rens        # fjern dupliserte QR-kodar
  python fiks-qr.py --debug       # list alle lenker (maks 20 sider)
"""

import io
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import asyncio
from datetime import datetime
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
    """Slett alle QR-bilete frå sida med redaksjon (fjerner biletdata heilt)."""
    rects = [
        pymupdf.Rect(img["bbox"])
        for img in page.get_image_info()
        if is_qr_candidate(pymupdf.Rect(img["bbox"]))
    ]
    if not rects:
        return 0
    for rect in rects:
        page.add_redact_annot(rect)
    page.apply_redactions()   # slettar både tekst og bilete i merkte område
    return len(rects)


def rens_pdf(pdf_path: Path) -> int:
    doc   = pymupdf.open(str(pdf_path))
    total = 0
    for page_num in range(len(doc)):
        total += rens_page(doc[page_num])
    if total > 0:
        tmp = str(pdf_path) + ".tmp"
        doc.save(tmp, garbage=4, deflate=True)
        doc.close()
        os.replace(tmp, str(pdf_path))
        print(f"  🧹 {pdf_path.name}: {total} QR-bilete fjerna")
    else:
        print(f"  –  {pdf_path.name}: ingen QR-bilete")
        doc.close()
    return total


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

    # Samle alle qr_rect-ar, tekstsoner og embed-lenke-data
    rects_to_insert: list[pymupdf.Rect] = []
    redact_zones:   list[pymupdf.Rect] = []
    saved_links:    list[dict]          = []   # gjenopprett etter redaksjon

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
        # Hopp over om ei overlappande qr_rect allereie er samla inn same runde
        if any(qr_rect.intersects(r) for r in rects_to_insert):
            continue

        # Finn alle tekstblokkar i heile embed-sona (frå topp av qr_rect til
        # ~20 pt under link_rect) og bygg ein samla redigeringssone
        scan = pymupdf.Rect(page.rect.x0, qr_rect.y0 - 5,
                            page.rect.x1, link_rect.y1 + 20)
        blocks = page.get_text("blocks", clip=scan)
        if blocks:
            xs0 = min(b[0] for b in blocks)
            ys0 = min(b[1] for b in blocks)
            xs1 = max(b[2] for b in blocks)
            ys1 = max(b[3] for b in blocks)
            zone = pymupdf.Rect(xs0 - 2, ys0 - 2, xs1 + 2, ys1 + 2)
        else:
            zone = qr_rect  # fallback

        rects_to_insert.append(qr_rect)
        redact_zones.append(zone)
        # Lagre embed-lenka så me kan setje ho inn att etter redaksjon
        saved_links.append({"kind": pymupdf.LINK_URI,
                             "from": link["from"],
                             "uri":  link["uri"]})

    if not rects_to_insert:
        return 0

    # Redakter alle soner, så set inn QR-bilete og gjenopprett embed-lenker
    for zone in redact_zones:
        page.add_redact_annot(zone)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    for qr_rect in rects_to_insert:
        page.insert_image(qr_rect, stream=qr_png)
    # Redaksjon fjernar lenke-annotasjonar i området — legg dei inn att
    for lk in saved_links:
        page.insert_link(lk)

    return len(rects_to_insert)


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
        # Må bruke full save (ikkje incremental) etter apply_redactions()
        tmp = str(pdf_path) + ".tmp"
        doc.save(tmp, garbage=4, deflate=True)
        doc.close()
        os.replace(tmp, str(pdf_path))
        print(f"  ✅ {pdf_path.name}: {total} QR-kodar sett inn")
    else:
        print(f"  –  {pdf_path.name}: ingen embed-boks funnen")
        doc.close()
    return total


def pick_folder() -> Path:
    args = [a for a in sys.argv[1:]
            if not a.startswith("--") and not a.startswith("http")]
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
    def _sort_key(p: Path) -> tuple:
        if p.stem == "0000_cover": return (0, p.stem)
        if p.stem == "0000_toc":   return (1, p.stem)
        return (2, p.stem)
    for f in sorted(sider_dir.glob("*.pdf"), key=_sort_key):
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




# ── Regenerer framsida med Playwright ────────────────────────────────────────

def _slug_to_title(url: str) -> str:
    """Gjer ndla.no-URL om til lesbar tittel via slug i stien."""
    # t.d. /e/kinesisk-1/introduksjon-til-kinesisk/e4fdb…  →  Introduksjon til kinesisk
    parts = [p for p in url.rstrip("/").split("/") if p]
    # Hopp over protocol, host, type-prefix (e/r/f) og ID (hex-streng sist)
    slug_parts = [p for p in parts[2:] if not re.fullmatch(r"[0-9a-f]{8,}", p)]
    if not slug_parts:
        return url
    slug  = slug_parts[-1]           # siste meiningsfulle segment
    prefix = "Emne: " if "/e/" in url else ""
    return prefix + slug.replace("-", " ").capitalize()


def _toc_from_json(sider_dir: Path) -> list[str] | None:
    """Les titlar frå toc.json viss fila finst."""
    import json
    toc_json = sider_dir.parent / "toc.json"
    if not toc_json.exists():
        return None
    try:
        data = json.loads(toc_json.read_text())
        # Støttar både gammalt format (liste) og nytt (dict med "articles")
        articles = data.get("articles", data) if isinstance(data, dict) else data
        return [item["title"] for item in articles]
    except Exception:
        return None


def _toc_titles_from_sider(sider_dir: Path) -> list[str]:
    """Trekk ut artikkeltitlar — fyrst frå toc.json, så frå PDF-metadata (title-felt)."""
    cached = _toc_from_json(sider_dir)
    if cached:
        return cached

    titles = []
    for p in sorted(sider_dir.glob("*.pdf")):
        if p.stem in ("0000_toc", "0000_cover"):
            continue
        title = p.stem  # fallback
        try:
            doc = pymupdf.open(str(p))
            t   = doc.metadata.get("title", "")
            doc.close()
            if t:
                title = t.removeprefix("NDLA | ").strip()
        except Exception:
            pass
        titles.append(title)
    return titles


def _font_face_css() -> str:
    """Returnerer @font-face CSS viss fontar finst i fonts/-mappa."""
    d    = Path(__file__).parent / "fonts"
    ss3  = d / "SourceSans3.ttf"
    sf4  = d / "SourceSerif4.ttf"
    sf4i = d / "SourceSerif4Italic.ttf"
    if not (ss3.exists() and sf4.exists()):
        return ""
    italic_src = f"url('file://{sf4i}')" if sf4i.exists() else f"url('file://{sf4}')"
    return f"""
@font-face {{
    font-family: 'Source Serif 4';
    src: url('file://{sf4}') format('truetype');
    font-weight: 100 900; font-style: normal;
}}
@font-face {{
    font-family: 'Source Serif 4';
    src: {italic_src} format('truetype');
    font-weight: 100 900; font-style: italic;
}}
@font-face {{
    font-family: 'Source Sans 3';
    src: url('file://{ss3}') format('truetype');
    font-weight: 100 900; font-style: normal;
}}
"""

PRINT_CSS_BASE = """
    :root {
        --ndla-blue:      #004785;
        --ndla-blue-dark: #003665;
        --ndla-grey-rule: #e0e0e0;
    }
    body {
        font-size: 11pt;
        font-family: 'Source Serif 4', Georgia, serif;
        line-height: 1.55;
        color: #111;
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Source Sans 3', system-ui, sans-serif;
        font-weight: 600;
        color: var(--ndla-blue-dark);
        page-break-after: avoid;
    }
    @page { size: A4; margin: 20mm; }
    img { max-width: 100%; }
    figure, .c-figure { page-break-inside: avoid; }
    pre, code { font-size: 9pt; font-family: monospace; }
    nav, .c-breadcrumb, footer { display: none !important; }
    a[href] { color: var(--ndla-blue); text-decoration: underline; }
    hr { border: none; border-top: 1px solid var(--ndla-grey-rule); margin: 1.2em 0; }
"""

def _print_css() -> str:
    return _font_face_css() + PRINT_CSS_BASE


def build_toc_html(toc: list, subject: str, generated_at: str, pdf_name: str = "") -> str:
    items  = "\n".join(f"<li>{t}</li>" for t, _, _, _ in toc)
    subj   = f"PDF-eksport-av-fag: {pdf_name}" if pdf_name else "PDF-eksport-av-fag"
    mailto = f"hjelp@ndla.no?subject={subj}"
    font_css = _font_face_css()
    return f"""<!DOCTYPE html>
<html lang="nb"><head><meta charset="utf-8"><style>
  {font_css}
  :root{{--ndla-blue:#004785;--ndla-blue-dark:#003665;}}
  body{{font-family:'Source Serif 4',Georgia,serif;padding:30px;font-size:11pt;line-height:1.55;color:#111;}}
  h1{{font-family:'Source Sans 3',sans-serif;font-size:20pt;font-weight:700;
      color:var(--ndla-blue-dark);margin-bottom:4px;}}
  .meta{{color:#555;font-size:10pt;margin-bottom:20px;font-family:'Source Sans 3',sans-serif;}}
  .disclaimer{{background:#f0f4fa;border-left:4px solid var(--ndla-blue);
    padding:10px 14px;font-size:10pt;color:#222;margin-bottom:14px;line-height:1.5;
    font-family:'Source Sans 3',sans-serif;}}
  .qr-info{{background:#fdf8ec;border-left:4px solid #c08000;
    padding:10px 14px;font-size:10pt;color:#222;margin-bottom:20px;line-height:1.5;
    font-family:'Source Sans 3',sans-serif;}}
  a{{color:var(--ndla-blue);}} ol{{margin-top:0;}}
  li{{padding:4px 0;font-size:11pt;font-family:'Source Sans 3',sans-serif;}}
  @page{{size:A4;margin:20mm;}}
</style></head><body>
  <h1>{subject}</h1>
  <p class="meta">Generert: {generated_at} &nbsp;·&nbsp; {len(toc)} artiklar</p>
  <ol>{items}</ol>
</body></html>"""


async def _regen_toc_async(folder: Path):

    sider_dir    = folder / "sider"
    toc_path     = sider_dir / "0000_toc.pdf"
    titles       = _toc_titles_from_sider(sider_dir)
    subject      = " ".join(w.capitalize() for w in folder.name.split("-")[:-3]) or folder.name
    generated_at = "-".join(folder.name.split("-")[-3:])   # yy-mm-dd
    pdf_name     = folder.name + ".pdf"

    # build_toc_html treng (tittel, filnamn, iframe_url, ndla_url) per rad
    toc = [(t, f"{i:04d}.pdf", "", "") for i, t in enumerate(titles, 1)]
    html = build_toc_html(toc, subject, generated_at, pdf_name)

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page    = await browser.new_page()
        await page.set_content(html, wait_until="load")
        await page.pdf(
            path=str(toc_path), format="A4", tagged=True,
            margin={"top": "20mm", "bottom": "20mm",
                    "left": "20mm", "right": "20mm"},
        )
        await browser.close()
    print(f"  ✅ 0000_toc.pdf regenerert ({len(titles)} artiklar)")


def regen_toc(folder: Path):
    asyncio.run(_regen_toc_async(folder))


async def fetch_subject_meta(client, subject_url: str) -> dict:
    """Hent OG-metadata frå /f/-sida (tittel, beskriving, bilete)."""
    import httpx as _httpx

    def _og(html: str, prop: str) -> str:
        m = re.search(
            rf'<meta\s[^>]*property=["\'\']og:{prop}["\'\'][^>]*content=["\'\']([^\"\'\']*)["\'\'][^>]*>',
            html, re.IGNORECASE,
        )
        if not m:
            m = re.search(
                rf'<meta\s[^>]*content=["\'\']([^\"\'\']*)["\'\'][^>]*property=["\'\']og:{prop}["\'\'][^>]*>',
                html, re.IGNORECASE,
            )
        return m.group(1).strip() if m else ""

    try:
        resp = await client.get(subject_url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        return {
            "title":       _og(html, "title"),
            "description": _og(html, "description"),
            "image_url":   _og(html, "image"),
        }
    except Exception as exc:
        print(f"  ⚠️  Klarte ikkje hente forsideinfo: {exc}")
        return {}


def build_cover_html(subject_url: str, meta: dict, generated_at: str,
                     article_count: int) -> str:
    """Bygg HTML for forsida basert på metadata frå /f/-sida."""
    font_css  = _font_face_css()
    title     = meta.get("title", "")
    desc      = meta.get("description", "")
    img_url   = meta.get("image_url", "")
    img_html  = (
        '<div class="cover-img-wrap"><img src="' + img_url + '" alt=""></div>'
    ) if img_url else ""
    desc_html = f'<p class="desc">{desc}</p>' if desc else ""
    return f"""<!DOCTYPE html>
<html lang="nb"><head><meta charset="utf-8"><style>
  {font_css}
  :root{{
    --kunnskap:        #2A1C5E;
    --kunnskap-dark:   #1A1040;
    --motivasjon:      #C8A4F7;
    --motivasjon-pale: #F9F6FE;
    --svart:           #18181B;
    --hvit:            #FFFFFF;
  }}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  html,body{{height:100%;}}
  body{{
    font-family:'Source Sans 3',system-ui,sans-serif;
    color:var(--svart);
    display:flex;flex-direction:column;height:100%;
    background:var(--hvit);
    -webkit-print-color-adjust:exact;
    print-color-adjust:exact;
  }}
  /* ── Topptekst ── */
  .cover-header{{
    background:var(--kunnskap);
    padding:52px 52px 48px;
    color:var(--hvit);
    flex-shrink:0;
    border-bottom:5px solid var(--motivasjon);
    -webkit-print-color-adjust:exact;
    print-color-adjust:exact;
  }}
  .ndla-wordmark{{
    font-size:9pt;font-weight:800;letter-spacing:0.28em;
    text-transform:uppercase;
    color:var(--motivasjon);
    margin-bottom:28px;
  }}
  h1{{
    font-size:38pt;font-weight:900;line-height:1.08;
    color:var(--hvit);
    font-family:'Source Sans 3',sans-serif;
    margin-bottom:20px;
    text-shadow:0 2px 8px rgba(0,0,0,0.45);
  }}
  .desc{{
    font-size:13.5pt;line-height:1.55;
    color:rgba(255,255,255,0.90);
    max-width:480px;
    font-weight:400;
  }}

  /* ── Bilete ── */
  .cover-img-wrap{{flex-shrink:0;overflow:hidden;max-height:260px;}}
  .cover-img-wrap img{{width:100%;height:260px;object-fit:cover;display:block;}}

  /* ── Merknadar ── */
  .spacer{{flex:1;min-height:12px;}}
  .notes{{padding:20px 52px 0;flex-shrink:0;}}
  .note-box{{
    padding:11px 15px;font-size:9.5pt;line-height:1.5;
    margin-bottom:10px;font-family:'Source Sans 3',sans-serif;
  }}
  .disclaimer{{
    background:var(--motivasjon-pale);
    border-left:4px solid var(--kunnskap);
    color:var(--svart);
  }}
  .qr-info{{background:var(--motivasjon-pale);border-left:4px solid var(--motivasjon);color:var(--svart);}}
  .notes a{{color:var(--kunnskap);}}

  /* ── Botnlinje ── */
  .cover-footer{{
    padding:18px 52px;
    border-top:2px solid var(--motivasjon-pale);
    background:var(--hvit);
    flex-shrink:0;
  }}
  .meta-row{{display:flex;gap:40px;align-items:flex-start;flex-wrap:wrap;}}
  .meta-label{{
    font-size:7.5pt;font-weight:800;text-transform:uppercase;
    letter-spacing:0.10em;color:var(--kunnskap);margin-bottom:3px;
  }}
  .meta-value{{font-size:10pt;color:#444;}}
  .meta-value a{{color:var(--kunnskap);text-decoration:none;}}

  @page{{size:A4;margin:0;}}
</style></head><body>
  <div class="cover-header">
    <div class="ndla-wordmark">NDLA</div>
    <h1>{title}</h1>
    {desc_html}
  </div>
  {img_html}
  <div class="notes">
    <div class="note-box disclaimer">
      <strong>Merk:</strong> Artiklane på <a href="https://ndla.no">ndla.no</a> kan ha
      blitt oppdaterte etter at denne PDF-en vart generert. Sjekk gjerne den originale
      artikkelen viss du oppdagar feil. Vil du melde frå om ein feil i PDFen, send
      e-post til <a href="mailto:hjelp@ndla.no">hjelp@ndla.no</a>.
    </div>
    <div class="note-box qr-info">
      <strong>Videoar, simuleringar og interaktivt innhald</strong><br>
      Denne PDF-en inneheld artiklar med innebygde videoar, simuleringar og andre
      interaktive element. Slikt innhald let seg ikkje vise i ein PDF, og er difor
      erstatta med ein QR-kode. Scan QR-koden med mobilen, så kjem du direkte til
      artikkelen på <a href="https://ndla.no">ndla.no</a> der du kan sjå og bruke innhaldet.
    </div>
  </div>
  <div class="spacer"></div>
  <div class="cover-footer">
    <div class="meta-row">
      <div><div class="meta-label">Generert</div>
           <div class="meta-value">{generated_at}</div></div>
      <div><div class="meta-label">Artiklar</div>
           <div class="meta-value">{article_count}</div></div>
      <div><div class="meta-label">Kjelde</div>
           <div class="meta-value">
             <a href="{subject_url}">{subject_url}</a>
           </div></div>
    </div>
  </div>
</body></html>"""


async def _regen_cover_async(folder: Path, cover_url: str | None = None):
    import httpx as _httpx
    import json
    from playwright.async_api import async_playwright

    sider_dir   = folder / "sider"
    cover_path  = sider_dir / "0000_cover.pdf"
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Les subject_url frå toc.json
    toc_json = folder / "toc.json"
    subject_url   = cover_url  # evt. overstyrt frå kommandolinja
    article_count = 0
    subject_meta  = {}
    if toc_json.exists():
        try:
            data = json.loads(toc_json.read_text())
            if isinstance(data, dict):
                subject_url   = data.get("subject_url")
                subject_meta  = data.get("subject_meta", {})
                article_count = len(data.get("articles", []))
        except Exception:
            pass

    if not subject_url:
        slug = "-".join(folder.name.split("-")[:-3]) or folder.name
        # Leita etter sitemap-fil i same mappe som skriptet
        script_dir = Path(__file__).parent
        sitemaps = sorted(script_dir.glob(f"sitemap-f-{slug}-*.txt"))
        if sitemaps:
            m = re.search(r'-([0-9a-f]{8,})$', sitemaps[0].stem)
            if m:
                subject_url = f"https://ndla.no/f/{slug}/{m.group(1)}"
        if not subject_url:
            subject_url = f"https://ndla.no/f/{slug}"

    if not subject_meta:
        print(f"  Hentar forsideinfo frå {subject_url} …")
        async with _httpx.AsyncClient() as client:
            subject_meta = await fetch_subject_meta(client, subject_url)

    if not article_count:
        article_count = len([p for p in sider_dir.glob("*.pdf")
                              if p.stem not in ("0000_toc", "0000_cover")])

    html = build_cover_html(subject_url, subject_meta, generated_at, article_count)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page    = await browser.new_page()
        await page.set_content(html, wait_until="load")
        await page.pdf(
            path=str(cover_path), format="A4", tagged=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        await browser.close()
    print(f"  ✅ 0000_cover.pdf regenerert ({subject_meta.get('title', subject_url)})")


def regen_cover(folder: Path, cover_url: str | None = None):
    asyncio.run(_regen_cover_async(folder, cover_url=cover_url))


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

    cover_url = next((a for a in sys.argv[1:]
                      if a.startswith("https://") or a.startswith("http://")),
                     None)

    if "--regen-all" in flags:
        print(f"\nRegenererer forside + innhaldsliste for {folder.name} …")
        regen_cover(folder, cover_url=cover_url)
        regen_toc(folder)
        remerge(folder)
        print("\n🎉 Ferdig.")
        return

    if "--regen-cover" in flags:
        print(f"\nRegenererer forsida for {folder.name} …")
        regen_cover(folder, cover_url=cover_url)
        remerge(folder)
        print("\n🎉 Ferdig.")
        return

    if "--regen-toc" in flags:
        print(f"\nRegenererer innhaldslista for {folder.name} …")
        regen_toc(folder)
        remerge(folder)
        print("\n🎉 Ferdig.")
        return

    pdfs = sorted(sider_dir.glob("*.pdf"))

    if "--rens" in flags:
        print(f"\nEksportmappe: {folder}/")
        print(f"Ryddar duplikat-QR i {len(pdfs)} sider …\n")
        total = sum(rens_pdf(p) for p in pdfs if p.stem not in ("0000_toc", "0000_cover"))
        if total > 0:
            remerge(folder)
            print(f"\n🎉 Ferdig — {total} duplikat(ar) fjerna.")
        else:
            print("\nℹ️  Ingen duplikat funne.")
        return

    pdf_name = folder.name + ".pdf"
    print(f"\nEksportmappe: {folder}/")
    print(f"Set inn QR-kodar i {len(pdfs)} sider (kampanjesporing: {pdf_name}) …\n")
    total = sum(fix_pdf(p, pdf_name) for p in pdfs if p.stem not in ("0000_toc", "0000_cover"))
    if total > 0:
        remerge(folder)
        print(f"\n🎉 Ferdig — {total} QR-kodar totalt.")
    else:
        print("\nℹ️  Ingen embed-boksane vart funne.")
        print("    Køyr med --debug for å sjå kva lenker som finst.")


if __name__ == "__main__":
    main()
