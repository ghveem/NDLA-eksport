# NDLA PDF-eksport — proof of concept

*Laga av [guttorm@ndla.no](mailto:guttorm@ndla.no)*

Genererer ein samla PDF av alle artiklar i eit NDLA-fag,
basert på ei sitemap-fil med NDLA-adresser.

Sitemap over alle fag på ndla.no ligg på <https://ndla.no/sitemap.xml>.
Her finn ein lenkjer til ei tekstfil med adresser til alle artiklar per fag.
Desse tekstfilene vert oppdaterte om lag éin gong i veka.

## Oppsett

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Framgangsmåte

1. Opne [https://ndla.no/sitemap.xml](https://ndla.no/sitemap.xml) og finn faget du vil eksportere
2. Last ned `.txt`-fila for faget til mappa der du køyrer scriptet
3. Køyr `python eksport.py` — scriptet finn sitemap-fila automatisk og spør om stadfesting
4. Er det fleire sitemap-filer i mappa, får du ein meny der du vel fag

Resultatet hamnar i ei undermappe på forma `fagnamn-yy-mm-dd/`,
til dømes `kinesisk-1-26-09-22/`, med den samanslåtte PDF-en inne i same mappe.

## Køyr

```bash
python eksport.py
```

Scriptet les sitemap-fila, hentar titlar og iframe-URL-ar via NDLA sitt
oEmbed-endepunkt, rendrar kvar artikkel til PDF med Playwright, og slår
alt saman til éin PDF med innhaldsliste fremst.

## Kva URL-typar er med?

| Type    | Prefix | Forklaring                        |
|---------|--------|-----------------------------------|
| Emne    | `/e/`  | Kapittel-/emneoversikt            |
| Ressurs | `/r/`  | Fagartikkel                       |
| Fag     | `/f/`  | Faget sjølv — **ikkje inkludert** |

Emneartiklar får prefiks `Emne:` i innhaldslista.

## Kva er med i kvar artikkel-PDF?

- **Innhald**: artikkelen rendra frå `article-iframe` (rein visning utan navigasjon)
- **Lenker**: alle lenker i artikkelen (inkl. «relatert innhald») er synlege og klikkbare
- **Nedst**: synleg URL til artikkelen på ndla.no

## Innhaldsliste (første side)

Viser generert dato/tid og ein ansvarsfraskrivingstekst:
artiklar på ndla.no kan ha blitt oppdaterte etter at PDFen vart generert.
Feil kan meldast til `hjelp@ndla.no` med emne `PDF-eksport-av-fag: <filnamn>.pdf` —
filnamnet inkluderer datoen for eksporten.

## Universell utforming (UU)

PDF-filer som vert publiserte, skal følgje WCAG 2.1 AA / PDF/UA-1 (ISO 14289).
Dette proof of concept produserer ikkje-tagga PDF (Playwright/Chrome-printer).

Tiltak for å betre tilgjengelegheita:

- **Tagging**: legg til `tagged=True` i `page.pdf()`-kalla når Playwright ≥ 1.42 er installert — bruker Chrome sitt tilgjengelegheitstret til å generere tagga PDF
- **Dokumentspråk**: artiklane frå ndla.no har `lang="nb"` i HTML
- **Dokumenttittel**: set tittel i PDF-metadata via PyMuPDF etter samanslåing
- **Alt-tekstar og tabelloverskrifter**: avheng av kjeldinnhaldet på ndla.no
- **Sjekk**: bruk [PAC (PDF Accessibility Checker)](https://pac.pdf-accessibility.org/) for automatisk WCAG-validering

## Sporing (Matomo)

QR-kodar og lenker i eksportert PDF bør ha MTM-parametrar:

```
?mtm_source=pdf-eksport&mtm_medium=lenke&mtm_campaign=min-ndla-mappe
```
