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

Prosjektet inneheld ei `fonts/`-mappe med Source Serif 4 og Source Sans 3
som vert brukte automatisk under eksport. Desse er henta frå Google Fonts
og ligg lokalt slik at renderinga ikkje er avhengig av internettilgang.

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

## Innebygd innhald (video, H5P, simuleringar)

Innhald som ikkje kan visast i PDF vert erstatta med ei boks:

| Kjelde       | Kva som visast                          |
|--------------|----------------------------------------|
| YouTube      | Thumbnail-bilde + klikkbar lenke       |
| Brightcove   | Posterbilete + klikkbar lenke          |
| H5P          | QR-kode til artikkelen på ndla.no      |
| Andre iframes| QR-kode til artikkelen på ndla.no      |

QR-kodar vert genererte lokalt med `segno`-biblioteket — ingen ekstern HTTP
nødvendig under rendering. Koden peikar til ndla.no-artikkelen (ikkje
embed-URL-en) slik at mobilbrukaren kjem til den rette sida.

## Framsida (innhaldsliste)

- Tittel, dato og tal artiklar
- **Ansvarsfraskrivingsboks**: åtvaring om at innhaldet kan vere utdatert
- **QR-forklaringsboks**: informerer lesaren om at videoar/simuleringar
  er erstatta med QR-kodar og korleis dei bruker dei

## Design og typografi

Eksportane bruker NDLA-brand:

| Element        | Font / farge                        |
|----------------|-------------------------------------|
| Brødtekst      | Source Serif 4 / fallback Georgia   |
| Overskrifter   | Source Sans 3 / fallback system-ui  |
| Lenker         | `#004785` (NDLA-blå)                |
| Overskriftsfarge | `#003665` (mørk NDLA-blå)         |

Fontane ligg i `fonts/` og vert lasta via `@font-face` med absolutte filstigar.
Viss `fonts/`-mappa manglar, faller scriptet stille attende til systemfontar.

## Sporing (Matomo)

Alle klikkbare ndla.no-lenker i PDF-en — inkludert QR-kodane — får automatisk
kampanjeparametrar:

```
?mtm_source=pdf-eksport&mtm_medium=<filnamn>.pdf
```

Filnamnet inneheld fagnamn og eksportdato, t.d. `kinesisk-1-26-09-22.pdf`.
Parametrane er ikkje synlege for lesaren, men loggast i Matomo når lenkene
vert klikka.

## Etterbehandling: fiks-qr.py

`fiks-qr.py` er eit separat script for å redigere eksisterande eksport-PDF-ar
utan å køyre heile eksporten på nytt.

```bash
# Set inn manglande QR-kodar (standard)
python fiks-qr.py

# Spesifiser mappe direkte
python fiks-qr.py kinesisk-1-26-09-22

# Legg til infoboksane på framsida
python fiks-qr.py --infoboks

# Fjern dupliserte QR-kodar (om scriptet er køyrt to gonger)
python fiks-qr.py --rens

# Debug: list alle lenker i dei 20 første artiklane
python fiks-qr.py --debug
```

Scriptet bruker PyMuPDF til å opne kvar enkelt side-PDF, finne embed-lenker
(h5p.ndla.no, YouTube, Brightcove o.l.), og setje inn QR-kodar over dei.
Artikkel-URL-en vert funnen i to omgangar — fyrst skannast alle sider etter
ein ndla.no-lenke, så vert QR-koden sett inn på sidene med embed. Dette
løyser problemet med at «Kjelde:»-lenka kan liggje på ei anna side enn sjølve
embed-boksen.

Etter endring på enkeltartiklar slår scriptet automatisk saman alle side-PDF-ar
til ein ny samla PDF (`fagnamn-dato.pdf`).

## Mappestruktur etter eksport

```
kinesisk-1-26-09-22/
├── kinesisk-1-26-09-22.pdf   ← samla PDF (det du deler)
└── sider/
    ├── 0000_toc.pdf           ← innhaldsliste / framsida
    ├── 0001.pdf
    ├── 0002.pdf
    └── …
```

## Universell utforming (UU)

Eksporten bruker `tagged=True` i Playwright sitt `page.pdf()`-kall, som
produserer PDF/UA-kompatibel tagging via Chrome sitt tilgjengelegheitstret.

Andre tiltak:
- Artiklane frå ndla.no har `lang="nb"` i HTML
- Lenker er merkte med `color:#004785` og `text-decoration:underline`

Tilrådd verktøy for validering: [PAC (PDF Accessibility Checker)](https://pac.pdf-accessibility.org/)
