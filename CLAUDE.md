# CLAUDE.md for NDLA-eksport

Proof of concept som lagar ein samla PDF av alle artiklar i eit NDLA-fag ut frå ei sitemap-fil. Sjå README.md for detaljar.

## Køyring

- Oppsett: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium`
- `python lag-pdf.py [sitemap-fil.txt]` køyrer `eksport.py` og deretter `fiks-qr.py`. Utan argument får du meny over `sitemap-*.txt` i mappa
- `python eksport.py` åleine gir PDF utan QR-etterbehandling
- `python fiks-qr.py [mappe]` set inn QR-kodar i ein eksisterande eksport utan å køyre alt på nytt. Flagg: `--rens`, `--debug`, `--regen-cover`, `--regen-toc` og `--regen-all` (lagar framside og/eller innhaldsliste på nytt og slår saman PDF-en). Flagget `--infoboks` i README.md finst ikkje i koden
- Sitemap-filer hentar me frå https://ndla.no/sitemap.xml (ei tekstfil per fag, oppdatert om lag ein gong i veka)

## Struktur

- `eksport.py`: les sitemap, rendrar kvar artikkel (`/e/` og `/r/`, ikkje `/f/`) med Playwright til PDF, lagar framside og samlar alt. Lenker får `mtm_source=pdf-eksport&mtm_medium=<filnamn>.pdf`
- `fiks-qr.py`: PyMuPDF. Erstattar H5P, YouTube, Brightcove og andre iframes med QR-kodar (segno, lokalt) som peikar til artikkelen på ndla.no
- `lag-pdf.py`: wrapper som køyrer dei to over
- `fonts/`: Source Serif 4 og Source Sans 3, lasta lokalt via `@font-face`. Manglar mappa, fell eksporten stille attende til systemfontar
- Utdata: `<fag>-yy-mm-dd/` med samla PDF og `sider/` (ei PDF per artikkel). Alt dette, og `sitemap-*.txt`, er i .gitignore

## Fallgruver

- `fiks-qr.py --rens` fjernar doble QR-kodar etter at skriptet vart køyrt to gonger
- Artikkel-URL kan ligge på ei anna side enn embed-boksen, derfor skannar `fiks-qr.py` i to omgangar
- PDF-en brukar `tagged=True` for UU. Valider med PAC etter endringar i rendering
- Eksporten er avhengig av ndla.no (oEmbed og `article-iframe`). Endringar i NDLA si markup kan bryte rendering
- `*.pdf` er i .gitignore, også `POC-fageksport-readme.pdf`

## Reglar

- Bruk git med små, tydelege commits
- Trygg .gitignore, ingen hemmelegheiter eller tokens i repoet
- Oppdater README.md når noko endrar seg
- Bruk /ndla-brand for UI. Fargar i eksporten: Kunnskap `#2A1C5E`, Motivasjon `#C8A4F7`, lenker `#004785`
- Skriv nynorsk, utan tankestrek, bruk «me» og «K.I.»
- Gjer berre det som er bede om, kvar endra linje skal følgje av oppgåva
