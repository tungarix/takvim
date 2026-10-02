# Sürüm güvenlik incelemeleri

Her `vX.Y.Z` sürümü yayımlanmadan önce, önceki sürümden bu yana değişen kod
güvenlik açısından incelenir ve sonuç bu klasöre `vX.Y.Z.md` olarak yazılır.
`release.yml` etiketli her sürümde önce `scripts/guvenlik_kapisi.py`'yi
çalıştırır: kayıt yoksa ya da güncel değilse derleme başlamaz.

## Sıra

1. Sürümü `ui/surum.py`'de yükselt, `CHANGELOG.md`'yi yaz, commit et.
2. Önceki etiketten bu yana olan farkı incele (`git diff vÖNCEKİ..HEAD`).
   Claude Code'da `/security-review` bu iş için kullanılır.
3. Açık yüksek/orta bulgu varsa önce düzelt, commit et, 2. adıma dön.
4. Kaydı yaz ve commit et. Bu commit'te kayıt dışında dosya olmasın.
5. Etiketle: `git tag vX.Y.Z && git push origin vX.Y.Z`.

İncelemeden sonra kayıt dışında bir dosya değişirse kapı kapanır: incelemeyi
yenile, `Kapsam:`'ın sonundaki commit'i güncelle.

## Kayıt biçimi

İlk üç alan kapının okuduğu satırlardır, gerisi serbest:

```markdown
# v1.6.0 güvenlik incelemesi

Sürüm: v1.6.0
Kapsam: v1.5.0..<incelenen commit, 7-40 karakter sha>
Sonuç: geçti

## Bulgular
- (yoksa "Yüksek/orta bulgu yok.")

## Kabul edilen riskler
- (varsa gerekçesiyle)
```

`Sonuç:` yalnız `geçti` olduğunda kapı açılır. Önceki etiket yoksa (ilk sürüm)
`Kapsam:`'ın başı `başlangıç` olur.
