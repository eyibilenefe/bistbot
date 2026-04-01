# BISTBot Mimari

## Guncel Durum

BISTBot su anda tek bir `FastAPI` prosesi icinde hem HTML sayfalarini hem JSON API'yi sunan, gercek BIST verisini `Yahoo Finance` uzerinden ceken ve arastirma snapshot'larini disk onbellege yazan bir research ve paper-trading uygulamasidir.

Bugunku aktif giris noktalari:

- `src/bistbot/main.py`: uygulama bootstrap'i
- `src/bistbot/web/routes.py`: server-rendered sayfalar
- `src/bistbot/api/routes.py`: JSON API
- `src/bistbot/storage/memory.py`: aktif runtime state ve is kurallari
- `src/bistbot/services/jobs.py`: arka plan veri yenileme isleri

Uygulama halen "manuel karar destekli" mantigi korur; gercek emir gondermez. Bunun yaninda gercek setup'lardan otomatik bir paper portfoy de turetebilir.

## Sistem Topolojisi

### 1. Delivery Layer

`FastAPI` iki yuzey sunar:

- Web:
  - `GET /`
  - `GET /dashboard`
  - `GET /backtest`
- API:
  - market, setup, pozisyon, backtest ve cache-refresh endpoint'leri

Web rotalari `Jinja2Templates` ile `src/bistbot/templates` altindaki sayfalari render eder. Tarayici tarafi davranis ve grafik cizimi `src/bistbot/static/app.js` ve `src/bistbot/static/app.css` ile saglanir.

### 2. Domain Layer

Temel veri modelleri `src/bistbot/domain/models.py` icinde dataclass olarak tutulur:

- `PriceBar`
- `ClusterDefinition`
- `StrategyDefinition`
- `StrategyScore`
- `SetupCandidate`
- `PortfolioPosition`
- `TradeRecord`
- `DashboardOverview`

Durum ve davranis etiketleri `src/bistbot/domain/enums.py` icindedir:

- `StrategyFamily`
- `SetupStatus`
- `PositionStatus`
- `ClusterFallbackMode`
- `CorporateActionType`
- `JobName`

### 3. Application State Layer

Gercek calisan depolama katmani su anda `InMemoryStore` sinifidir. `src/bistbot/storage/base.py` icindeki `StorageRepository` protocol'u store'un sundugu arayuzu tanimlar; `api/routes.py` ve `web/routes.py` bu arayuze dayanir.

`InMemoryStore` su verileri bellekte tutar:

- sembol-sektor eslesmeleri
- gunluk veya arastirma amacli bar verileri
- cluster tanimlari
- strateji tanimlari ve skorlar
- aktif setup'lar
- acik ve kapali paper pozisyonlar
- backtest trade gecmisi
- son arastirma snapshot zamani

### 4. Provider Layer

Piyasa verisi `src/bistbot/providers/yahoo.py` icindeki `YahooFinanceBISTProvider` ile alinir.

Bu katman:

- sembol listesini `company_universe.py` uzerinden bilir
- sektor bilgisini Yahoo verisinden cozer ve cache'ler
- `1d` ve `1h` veriyi dogrudan indirir
- `4h` veriyi `1h` barlardan turetir
- bar verisini `.cache/bistbot/bars/...` altina disk cache olarak yazar

`main.py` icinde `enable_real_market_data=True` ise provider otomatik baglanir.

### 5. Persistence ve Cache Layer

Su anki aktif persistence bir veritabani degil, `DiskCache` tabanli JSON cache yapisidir:

- `.cache/bistbot/runtime_state.json`
- `.cache/bistbot/research_state.json`
- `.cache/bistbot/bars/<timeframe>/<symbol>.json`

`InMemoryStore` acilis sirasinda once runtime state'i, sonra research state'i yuklemeyi dener. Boylece uygulama her yeniden basladiginda tum veriyi bastan indirmek zorunda kalmaz.

`src/bistbot/storage/sql/schema.sql` repoda duruyor ama bugunku runtime'a bagli degildir. Bu dosya, ileride DB-backed repository'ye gecis icin referans bir schema niteligindedir; aktif veri yolu su anda JSON cache + bellek durumudur.

## Uygulama Baslatma Akisi

`create_app()` akisi su sekildedir:

1. `Settings` nesnesi olusturulur.
2. Gercek veri aciksa `YahooFinanceBISTProvider` initialize edilir.
3. `InMemoryStore` kurulur.
4. `JobService` uygulama state'ine eklenir.
5. `/static` mount edilir.
6. Web ve API router'lari kaydedilir.

`InMemoryStore` normal calisma modunda su bootstrap adimlarini uygular:

1. Kalici runtime state'i yuklemeyi dener.
2. Kalici research snapshot'unu yuklemeyi dener.
3. Provider varsa guncel sembol ve sektor metadata'sini birlestirir.
4. Pozisyon aciklamalarini ve olasilik metadata'sini backfill eder.
5. Otomatik paper trading aciksa portfoyu ilk acilista gunceller.

Istenirse `seed_demo_data=True` ile yalniz demo veri ureten mod da vardir.

## Arastirma Motoru

Arastirma snapshot'u `src/bistbot/services/research.py` icindeki `build_real_research_state()` tarafindan uretilir.

Varsayilan ayarlar `src/bistbot/config.py` icinde tanimlidir:

- `research_timeframe = "4h"`
- `backtest_lookback_days = 730`
- `walk_forward_train_days = 60`
- `walk_forward_test_days = 30`
- `walk_forward_step_days = 30`
- `min_cluster_size = 8`

Motorun akisi:

1. Provider'dan sembol ve sektor listesi cekilir.
2. Her sembol icin yeterli lookback bar'i indirilir.
3. EMA, RSI, ATR, ATR%, hacim orani, ROC, MACD ve breakout seviyeleri hesaplanir.
4. Son bilinen ATR60% degerleriyle point-in-time snapshot'lar uretilir.
5. `sector x volatility bucket` temelli cluster'lar olusturulur.
6. Walk-forward pencereleri uzerinden train/test simulasyonu yapilir.
7. Her cluster ve strateji ailesi icin OOS trade kayitlari ve metrikler toplanir.
8. Skorlar cluster bazinda normalize edilir.
9. Aktif stratejiler secilir.
10. Setup candidate'lar uretilir ve quality gate'den gecirilir.

## Point-in-Time Clustering

Kumeleme `src/bistbot/services/clustering.py` icinde uygulanir.

Kurallar:

- Snapshot'lar yalniz `as_of` tarihine kadar bilinen veriyle hesaplanir.
- Her sektor kendi icinde ATR60% degerine gore `low`, `mid`, `high` bucket'larina ayrilir.
- Bucket sayisi `min_cluster_size` altina dusunce once komsu volatilite bucket ile birlesme olur.
- Yine yetersiz kalirsa sektor bazli tek cluster'a dusulur.

Fallback modlari:

- `none`
- `adjacent_volatility_merge`
- `sector_only`

Walk-forward test pencerelerinde cluster assignment train sonuna gore dondurulur; gelecekteki volatilite rejimi gecmise yazilmaz.

## Skorlama ve Strateji Secimi

Normalization `src/bistbot/services/normalization.py` icindedir:

- `n >= 30` ise winsorized z-score
- `n < 30` ise percentile rank

Composite score `src/bistbot/services/scoring.py` icinde hesaplanir:

- `0.4 * normalized_return`
- `0.2 * normalized_win_rate`
- `0.3 * normalized_profit_factor`
- `-0.18 * normalized_max_drawdown`
- `%20` ustu drawdown icin ek ceza
- `%30` ustu max drawdown stratejiyi otomatik olarak gorunmez yapar

Aktif strateji secimi `src/bistbot/services/strategy_selection.py` icindedir. Bir stratejinin secilebilmesi icin:

- en az `12` OOS trade
- son alti pencerede en az `2` aktif pencere
- `avg_trade_return >= 1.25 x estimated_round_trip_cost`
- max drawdown junk threshold'un altinda kalma

Secim sirasinda:

- aile cesitliligi korunur
- pairwise OOS return correlation `< 0.75` olmalidir
- varsayilan maksimum aktif strateji sayisi `3`'tur

## Setup Uretimi ve Yasam Dongusu

Setup adaylari research snapshot sonunda uretilir. Kalite filtresi `quality_gate()` ile uygulanir.

Bugunku varsayilan setup filtreleri:

- ilk `%20` dilim
- minimum `3` setup tut
- `expected_r >= 1.5`
- `confluence_score >= 0.65`
- varsayilan setup omru `6 saat`

Confluence score agirliklari:

- daily regime `0.30`
- trend signal `0.25`
- momentum signal `0.20`
- volume confirmation `0.15`
- entry zone proximity `0.10`

Setup durumlari:

- `active`
- `approved_pending_entry`
- `rejected`
- `expired`
- `invalidated`
- `entered`
- `closed`

Kurallar `src/bistbot/services/setup_lifecycle.py` icindedir. Setup:

- suresi dolarsa `expired`
- daily regime bozulursa `invalidated`
- entry zone `0.5 ATR` disina tasarsa `invalidated`
- stop mantigi bozulursa `invalidated`

Manuel entry oncesinde setup bir kez daha dogrulanir.

## Risk, Pozisyon ve Paper Trading

Pozisyon buyuklugu `src/bistbot/services/risk.py` ile hesaplanir:

- risk bazli sizing
- varsayilan `risk_per_trade = 0.01`
- long islem icin `entry_price > stop_price` olmasi gerekir

Portfoy constraint'leri:

- sektor basina max `2` pozisyon
- max sektor maruziyeti `%40`
- max korelasyon `0.75`
- toplam portfoy riski `%5`

Paper trading akisi `InMemoryStore` icinde tutulur:

- `approve_setup()` ve `reject_setup()` setup kararini yazar
- `create_manual_position()` manuel girisi validate eder ve constraint kontrolu yapar
- `auto_paper_trading_enabled` aciksa yenileme sonunda otomatik paper entry yapilabilir
- refresh basina en fazla `5` yeni pozisyon acilir
- acik pozisyonlar varsayilan her `120` saniyede bir guncellenir

Pozisyon guncelleme davranislari:

- fiyat `1R` ilerlerse stop breakeven'a cekilir
- fiyat `2R` ilerlerse stop `+1R` seviyesine cekilir
- hedefe gelindiginde soft-limit kurali pozisyonu acik tutmaya izin vermezse pozisyon kapanir
- `7` gun soft limit sonrasi sadece `daily close > EMA20 > EMA50` ise pozisyon korunur

## Corporate Action ve Veri Kalitesi

Corporate action ayarlari `src/bistbot/services/portfolio_adjustments.py` icindedir:

- split ve bonus durumunda adet carpilir, anchor fiyatlar bolunur
- cash dividend durumunda fiyat anchor'lari asagi ayarlanir ve nakit bakiyesi artar

Veri kalitesi kontrolleri `src/bistbot/services/data_quality.py` icindedir:

- aciklanamayan gap'ler tespit edilir
- ayni gunde corporate action varsa gap kabul edilir
- aksi halde `unexplained_gap` eventi uretilir

Bu katman su an research refresh akisinin merkezi parcasindan cok destekleyici servis niteligindedir.

## Dashboard ve Backtest Sayfalari

Web yuzeyi store'un sayfa-verisi helper'larini kullanir.

`get_dashboard_page_data()` su bolumleri besler:

- overview kartlari
- gercek piyasa watchlist'i
- top setup kartlari
- acik pozisyon tablosu
- strateji insight listeleri
- canli trade grafik payload'lari

`get_backtest_page_data()` su bolumleri besler:

- cluster siralamasi
- hisse bazli backtest ozeti
- lider ve zayif strateji insight'lari
- recent trades listesi
- secilebilir backtest sembol browser'i
- trade chart payload'lari

Grafik payload'lari `src/bistbot/services/charting.py` ile uretilir. Frontend bu payload'lari tarayici tarafinda render eder.

## Cache Refresh ve Background Isler

Anlik veri yenileme iki asamada calisir:

1. `POST /api/cache/refresh`
2. `GET /api/cache/refresh/{job_id}`

`JobService.start_refresh()` tekil bir refresh isi olusturur ve arka planda thread baslatir. Bu is:

- progres bilgisini tutar
- ayni anda birden fazla refresh calismasini engeller
- tamamlandiginda sonucu ve hata bilgisini store eder

`POST /api/jobs/{job_name}/run` endpoint'i ise simdilik stub nitelikli manuel job kaydi uretir.

## Guncel API Yuzeyi

Aktif JSON API endpoint'leri:

- `GET /api/dashboard/overview`
- `GET /api/market/symbols`
- `GET /api/market/charts/{symbol}`
- `GET /api/setups/top`
- `GET /api/setups/{setup_id}`
- `POST /api/setups/{setup_id}/approve`
- `POST /api/setups/{setup_id}/reject`
- `POST /api/positions/manual-entry`
- `PATCH /api/positions/{position_id}`
- `GET /api/positions`
- `GET /api/backtests/clusters`
- `GET /api/backtests/symbols`
- `GET /api/backtests/symbols/{symbol}`
- `GET /api/backtests/clusters/{cluster_id}/strategies`
- `GET /api/backtests/strategies/{strategy_id}/trades`
- `POST /api/jobs/{job_name}/run`
- `POST /api/cache/refresh`
- `GET /api/cache/refresh/{job_id}`

## Test Stratejisi

Testler `tests/` altinda yer alir ve ana davranislari kapsar:

- clustering
- normalization
- scoring ve strategy selection
- costs
- setup lifecycle
- risk ve portfolio adjustments
- charting
- research build akisi
- API endpoint smoke test'leri
- paper trading davranislari

## Mimari Karari Ozeti

Bugunku mimari, DB-first bir sistemden cok "FastAPI + in-memory application state + disk cache + real market provider" modelidir. Bunun avantajlari:

- hizli yerel gelistirme
- sifira yakin kurulum maliyeti
- cache uzerinden hizli yeniden baslatma
- tek process icinde UI, API ve research mantiginin birlikte calismasi

Bugunku trade-off ise application state'in halen repository/veritabani ayrimina tam tasinmamis olmasidir. `StorageRepository` protocol'u ve `schema.sql`, ileride kalici DB-backed mimariye gecis icin hazir bir gecis noktasi sunar.
