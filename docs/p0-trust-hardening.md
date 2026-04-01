# BISTBot P0 Trust Hardening Note

## Root causes

- Setup ve position verileri API ile dashboard tarafinda farkli sekillerde serilestiriliyordu.
- Pozisyon gerekcesi string snapshot olarak tutuldugu icin stop/target degistikten sonra metin geride kaliyordu.
- Pozisyonlar giris anindaki setup baglamini kalici olarak saklamadigi icin confidence ve expected R backfill'i sembol bazli heuristige dusuyordu.
- `NaN` ve diger non-finite sayilar watchlist ve chart payload'larina sizabiliyor, hatta JSON serialization hatasi uretebiliyordu.
- Trailing stop mantigi mutable stop uzerinden yeniden risk hesapladigi icin `+1R` gecisi deterministik degildi.

## Refactor boundaries

- Yeni ortak katman `src/bistbot/services/presentation.py` icinde toplandi.
- `InMemoryStore` ham domain objelerini koruyor; API ve dashboard icin ortak setup/position/event view'lari uretiyor.
- Pozisyona additive entry-context alanlari eklendi:
  - `source_setup_id`
  - `initial_stop_price`
  - `initial_target_price`
  - `expected_r_at_entry`
  - `confidence_at_entry`
- Lifecycle event kaydi local/runtime-state seviyesinde tutuluyor; sonraki DB gecisine uyumlu kalacak sekilde ayri bir model olarak eklendi.

## Intentionally not changed

- Broker entegrasyonu veya canli order routing eklenmedi.
- Research, clustering, scoring ve strategy selection mantigi kalibre edilmedi.
- Confidence sunumu daha istatistiksel bir modele tasinmadi; bu P1 konusu olarak birakildi.
- StorageRepository arkasina DB-backed implementasyon eklenmedi.
- Tek-process FastAPI + web + API topolojisi korunudu.

## Migration note

- Runtime state shape'i additive olarak genisladi.
- Eski cache dosyalari halen okunabiliyor; yeni alanlar yoksa backfill ile dolduruluyor.
- Yeni `lifecycle_events` listesi runtime state'e yaziliyor.
- Eski pozisyon kayitlari yeni entry-context alanlarina sahip degilse setup/symbol iliskisi ve mevcut anchor'lar uzerinden hydrate ediliyor.
