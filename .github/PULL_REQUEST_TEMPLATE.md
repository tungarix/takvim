<!-- English or Turkish, both are fine. / Türkçe ya da İngilizce, ikisi de olur. -->

## What and why · Ne ve neden

<!-- One or two sentences. Link the issue: "Closes #123". -->
<!-- Bir iki cümle. İlgili issue'yu bağla: "Closes #123". -->

## Checklist · Kontrol listesi

- [ ] I opened or found an issue for this and it fits Takvim's scope (no server/accounts, sync, RSVP, mobile, CalDAV). / Bunun için bir issue var ve Takvim'in kapsamına uyuyor.
- [ ] `python -m ruff check .`, `python -m mypy core store`, `python -m pytest -q` and `node --check ui/static/app.js` pass. / Dördü de geçiyor.
- [ ] New behaviour has its own test; for a critical path I checked that the test fails when the code is broken. / Yeni davranışın kendi testi var; kritik yolda kodu bozunca testin kırıldığını gördüm.
- [ ] `core/` still imports nothing from `store/`, `ics/` or `ui/`. / `core/` hâlâ `store/`, `ics/`, `ui/` import etmiyor.
- [ ] If I changed the schema: a new numbered file in `store/migrations/` plus the same change in `store/schema.sql`; no existing migration was edited. / Şema değiştiyse: yeni migration dosyası + `schema.sql`; mevcut migration'a dokunulmadı.
- [ ] User-visible change: a line added under `## [Yayınlanmamış]` in `CHANGELOG.md`. / Kullanıcının göreceği değişiklik için CHANGELOG'a satır eklendi.
- [ ] README / AGENTS.md updated where they describe the changed behaviour. / Değişen davranışı anlatan yerlerde README / AGENTS.md güncellendi.
- [ ] No `.venv/`, `*.db` or personal data in the diff. / Diff'te `.venv/`, `*.db` ya da kişisel veri yok.
