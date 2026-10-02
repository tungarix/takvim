"""Sürüm güvenlik kapısı: `scripts/guvenlik_kapisi.py`.

Her test geçici bir git deposu kurar: `v1.0.0` → özellik commit'i →
inceleme kaydı → `v1.1.0`. Kapı yalnızca kayıt tam ve güncelken geçmeli.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.guvenlik_kapisi import KLASOR, denetle, main


def _git(repo: Path, *args: str) -> str:
    sonuc = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return sonuc.stdout.strip()


def _yaz(repo: Path, yol: str, metin: str) -> None:
    dosya = repo / yol
    dosya.parent.mkdir(parents=True, exist_ok=True)
    dosya.write_text(metin, encoding="utf-8")


def _commit(repo: Path, mesaj: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", mesaj)
    return _git(repo, "rev-parse", "HEAD")


def _kayit(surum: str, kapsam: str, sonuc: str = "geçti") -> str:
    return f"# {surum} güvenlik incelemesi\n\nSürüm: {surum}\nKapsam: {kapsam}\nSonuç: {sonuc}\n"


def _depo(tmp_path: Path, *, kayit: str | None = None) -> tuple[Path, str]:
    """`v1.0.0`, özellik commit'i ve (verilirse) kaydı olan depo; incelenen sha'yı döndürür."""
    repo = tmp_path / "depo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _yaz(repo, "core/a.py", "x = 1\n")
    _commit(repo, "ilk")
    _git(repo, "tag", "v1.0.0")
    _yaz(repo, "core/b.py", "y = 2\n")
    incelenen = _commit(repo, "özellik")
    if kayit is not None:
        _yaz(repo, f"{KLASOR}/v1.1.0.md", kayit.replace("SHA", incelenen))
        _commit(repo, "güvenlik incelemesi")
    return repo, incelenen


def test_kayit_tam_ve_guncelse_gecer(tmp_path: Path) -> None:
    repo, _ = _depo(tmp_path, kayit=_kayit("v1.1.0", "v1.0.0..SHA"))
    _git(repo, "tag", "v1.1.0")
    assert denetle(repo, "v1.1.0") == []


def test_kayit_yoksa_durdurur(tmp_path: Path) -> None:
    repo, _ = _depo(tmp_path)
    _git(repo, "tag", "v1.1.0")
    hatalar = denetle(repo, "v1.1.0")
    assert len(hatalar) == 1 and "etiketin içinde yok" in hatalar[0]


def test_sonuc_gecti_degilse_durdurur(tmp_path: Path) -> None:
    repo, _ = _depo(tmp_path, kayit=_kayit("v1.1.0", "v1.0.0..SHA", sonuc="kaldı"))
    _git(repo, "tag", "v1.1.0")
    assert any("Sonuç" in h for h in denetle(repo, "v1.1.0"))


def test_surum_alani_etiketle_uyusmazsa_durdurur(tmp_path: Path) -> None:
    repo, _ = _depo(tmp_path, kayit=_kayit("v1.0.9", "v1.0.0..SHA"))
    _git(repo, "tag", "v1.1.0")
    assert any("Sürüm" in h for h in denetle(repo, "v1.1.0"))


def test_kapsam_onceki_etiketten_baslamazsa_durdurur(tmp_path: Path) -> None:
    repo, _ = _depo(tmp_path, kayit=_kayit("v1.1.0", "v0.9.0..SHA"))
    _git(repo, "tag", "v1.1.0")
    assert any("v1.0.0" in h for h in denetle(repo, "v1.1.0"))


def test_incelemeden_sonra_kod_degisirse_durdurur(tmp_path: Path) -> None:
    repo, _ = _depo(tmp_path, kayit=_kayit("v1.1.0", "v1.0.0..SHA"))
    _yaz(repo, "core/b.py", "y = 3  # incelenmedi\n")
    _commit(repo, "son dakika değişikliği")
    _git(repo, "tag", "v1.1.0")
    hatalar = denetle(repo, "v1.1.0")
    assert len(hatalar) == 1 and "core/b.py" in hatalar[0]


def test_incelenen_commit_etiketin_gecmisinde_degilse_durdurur(tmp_path: Path) -> None:
    repo, ana = _depo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "yan", "v1.0.0")
    _yaz(repo, "core/c.py", "z = 4\n")
    yan = _commit(repo, "yan dal")
    _git(repo, "checkout", "-q", ana)
    _yaz(repo, f"{KLASOR}/v1.1.0.md", _kayit("v1.1.0", f"v1.0.0..{yan}"))
    _commit(repo, "yan dalı gösteren kayıt")
    _git(repo, "tag", "v1.1.0")
    assert any("geçmişinde değil" in h for h in denetle(repo, "v1.1.0"))


def test_kayit_calisma_klasorunde_olup_etikette_yoksa_durdurur(tmp_path: Path) -> None:
    repo, incelenen = _depo(tmp_path)
    _git(repo, "tag", "v1.1.0")
    _yaz(repo, f"{KLASOR}/v1.1.0.md", _kayit("v1.1.0", f"v1.0.0..{incelenen}"))
    hatalar = denetle(repo, "v1.1.0")
    assert len(hatalar) == 1 and "etiketin içinde yok" in hatalar[0]


def test_main_kapali_kapida_bir_doner(tmp_path: Path, monkeypatch) -> None:
    repo, _ = _depo(tmp_path)
    _git(repo, "tag", "v1.1.0")
    monkeypatch.chdir(repo)
    assert main(["v1.1.0"]) == 1
    assert main([]) == 2
