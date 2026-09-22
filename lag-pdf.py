#!/usr/bin/env python3
"""
lag-pdf.py – køyr eksport + QR-fiks i éin kommando

Bruk:
    python lag-pdf.py              # vel sitemap interaktivt
    python lag-pdf.py sitemap-f-kinesisk-1-*.txt
"""
import subprocess, sys, os
from pathlib import Path

HERE = Path(__file__).parent

def run(*args, **kwargs):
    result = subprocess.run(args, cwd=HERE, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)

def newest_export_folder(before: set[Path]) -> Path | None:
    """Finn mappa som vart oppretta under eksport."""
    after = set(Path(HERE).glob("*-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]"))
    new   = after - before
    if new:
        return sorted(new)[-1]
    # Fallback: nyaste eksisterande mappe
    candidates = sorted(after)
    return candidates[-1] if candidates else None

def main():
    # Sitemap frå arg eller interaktivt
    sitemap_arg = [a for a in sys.argv[1:] if not a.startswith("-")]

    print("╔══════════════════════════════════════╗")
    print("║  NDLA PDF-eksport                    ║")
    print("╚══════════════════════════════════════╝\n")

    # ── Steg 1: eksport ──────────────────────────────────────────────────────
    print("── Steg 1/2: Eksporterer fag ─────────────────────────────────\n")
    before = set(Path(HERE).glob("*-[0-9][0-9]-[0-9][0-9]-[0-9][0-9]"))

    eksport_args = [sys.executable, "eksport.py"]
    if sitemap_arg:
        # Legg til sitemap-arg så pick_sitemap kan plukke den opp
        # (eksport.py les sys.argv sjølv – vi set env-variabel)
        os.environ["NDLA_SITEMAP"] = sitemap_arg[0]
    run(*eksport_args)

    # ── Steg 2: QR-fiks ──────────────────────────────────────────────────────
    folder = newest_export_folder(before)
    if not folder:
        print("\n❌  Fann ingen eksportmappe etter eksport.")
        sys.exit(1)

    print(f"\n── Steg 2/2: Fiksar QR-kodar i {folder.name} ────────────────\n")
    run(sys.executable, "fiks-qr.py", str(folder))

    print(f"\n✅  Alt ferdig → {folder}/{folder.name}.pdf")

if __name__ == "__main__":
    main()
