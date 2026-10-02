"""Sürüm güvenlik kapısı.

Bir `vX.Y.Z` etiketi yayımlanmadan önce o sürümün güvenlik incelemesi
`guvenlik/incelemeler/vX.Y.Z.md` dosyasında kayıtlı olmalı. Bu betik
`release.yml`'in ilk adımında çalışır ve şu durumlarda sürümü durdurur:

- kayıt yok;
- `Sürüm:` alanı etiketle aynı değil ya da `Sonuç:` alanı `geçti` değil;
- `Kapsam:` önceki sürüm etiketinden başlamıyor (eski bir inceleme);
- incelenen commit'ten etikete kadar inceleme kayıtları dışında dosya değişmiş.

Kaydın başlığı (biçim için `guvenlik/incelemeler/README.md`):

    Sürüm: v1.6.0
    Kapsam: v1.5.0..<incelenen commit>
    Sonuç: geçti

Kullanım: `python scripts/guvenlik_kapisi.py v1.6.0` (depo kökünde).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

KLASOR = "guvenlik/incelemeler"
ILK_SURUM = "başlangıç"  # önceki etiket yoksa Kapsam'ın başı
_ALAN = re.compile(r"^(Sürüm|Kapsam|Sonuç):\s*(.+?)\s*$")
_KAPSAM = re.compile(r"^(\S+)\.\.([0-9a-fA-F]{7,40})$")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def onceki_etiket(repo: Path, etiket: str) -> str | None:
    """`etiket`'ten önceki en yakın `v*` etiketi; yoksa None."""
    sonuc = _git(repo, "describe", "--tags", "--abbrev=0", "--match", "v*", f"{etiket}^")
    return sonuc.stdout.strip() if sonuc.returncode == 0 else None


def denetle(repo: Path, etiket: str) -> list[str]:
    """Kapı geçerse boş liste döner; her eleman bir red gerekçesidir."""
    repo = Path(repo)
    if _git(repo, "rev-parse", "--verify", "--quiet", f"{etiket}^{{commit}}").returncode:
        return [f"'{etiket}' etiketi bu depoda yok."]

    # Kayıt, çalışma klasöründen değil etiketlenen commit'in içinden okunur.
    kayit = _git(repo, "show", f"{etiket}:{KLASOR}/{etiket}.md")
    if kayit.returncode:
        return [f"{KLASOR}/{etiket}.md etiketin içinde yok: önce incelemeyi yazıp commit et."]

    alanlar: dict[str, str] = {}
    for satir in kayit.stdout.splitlines():
        eslesme = _ALAN.match(satir)
        if eslesme:
            alanlar.setdefault(eslesme[1], eslesme[2])

    hatalar: list[str] = []
    if alanlar.get("Sürüm") != etiket:
        hatalar.append(f"'Sürüm:' alanı '{etiket}' olmalı, kayıtta: {alanlar.get('Sürüm')!r}.")
    if alanlar.get("Sonuç") != "geçti":
        hatalar.append(f"'Sonuç:' alanı 'geçti' değil (kayıtta: {alanlar.get('Sonuç')!r}).")

    kapsam = _KAPSAM.match(alanlar.get("Kapsam", ""))
    if not kapsam:
        hatalar.append("'Kapsam:' alanı '<önceki etiket>..<incelenen commit>' biçiminde olmalı.")
        return hatalar

    bas, incelenen = kapsam[1], kapsam[2]
    beklenen_bas = onceki_etiket(repo, etiket) or ILK_SURUM
    if bas != beklenen_bas:
        hatalar.append(f"Kapsam '{beklenen_bas}' etiketinden başlamalı, kayıtta: '{bas}'.")

    if _git(repo, "rev-parse", "--verify", "--quiet", f"{incelenen}^{{commit}}").returncode:
        hatalar.append(f"İncelenen commit '{incelenen}' bu depoda yok.")
        return hatalar
    if _git(repo, "merge-base", "--is-ancestor", incelenen, etiket).returncode:
        hatalar.append(f"İncelenen commit '{incelenen}', '{etiket}' etiketinin geçmişinde değil.")
        return hatalar

    degisen = _git(repo, "diff", "--name-only", "-z", incelenen, etiket).stdout.split("\0")
    incelenmemis = [yol for yol in degisen if yol and not yol.startswith(KLASOR + "/")]
    if incelenmemis:
        ornek = ", ".join(incelenmemis[:10])
        hatalar.append(
            f"İncelemeden sonra {len(incelenmemis)} dosya değişmiş ({ornek}): incelemeyi yenile."
        )
    return hatalar


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Kullanım: python scripts/guvenlik_kapisi.py vX.Y.Z")
        return 2
    etiket = args[0]
    hatalar = denetle(Path.cwd(), etiket)
    if hatalar:
        print(f"Güvenlik kapısı KAPALI ({etiket}):")
        for hata in hatalar:
            print(f"  - {hata}")
        return 1
    print(f"Güvenlik kapısı geçti: {KLASOR}/{etiket}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
