# NDLA PDF-eksport — proof of concept

Genererer ein samla PDF av alle artiklar i eit NDLA-fag,
basert på ei sitemap-fil med NDLA-adresser.

## Oppsett

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Køyr

```bash
python eksport.py
```

Scriptet les `sitemap-f-matematikk-2p-36bbf8f78d78.txt`,
hentar titlar og iframe-URL-ar via NDLA sitt oEmbed-endepunkt,
rendrar kvar artikkel til PDF med Playwright, og
slår alt saman til `matematikk-2p.pdf` med innhaldsliste fremst.

### Kva URL-typar er med?

| Type | Prefix | Forklaring |
|------|--------|------------|
| Emne | `/e/`  | Kapittel-/emneoversikt |
| Ressurs | `/r/` | Fagartikkel |
| Fag | `/f/` | Faget sjølv — **ikkje inkludert** |

## Sporing (Matomo)

QR-kodar og lenker i eksportert PDF bør ha MTM-parametrar:

```
?mtm_source=pdf-eksport&mtm_medium=lenke&mtm_campaign=min-ndla-mappe
```

## Initialisering av git

```bash
git init
git add .
git commit -m "init: NDLA PDF-eksport POC"
```
