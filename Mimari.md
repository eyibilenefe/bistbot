# BISTBot v1 Mimari

## System Overview

BISTBot, Borsa Istanbul icin manuel karar destekli, swing trading odakli bir quant research platformudur. Sistem otomatik emir gondermez; setup uretir, backtest yapar, risk hesaplar ve kullanicinin manuel girdigi pozisyonlari takip eder.

Teknik yapi:

- `FastAPI` tabanli API uygulamasi
- Python servis katmani ile quant logic
- PostgreSQL odakli veri modeli
- `strategy_runs` ve `strategy_scores` icin aylik native partitioning
- Dashboard ve Backtest yuzeyi icin API-first tasarim

V1 scope:

- Point-in-time cluster bazli strateji arastirmasi
- Quality-gated setup uretimi
- Manual-entry revalidation
- Corporate action aware portfoy takibi
- Portfolio-level risk enforcement

## Point-in-Time Research Model

Cluster mantigi `sector x 60-trading-day ATR% volatility tercile` uzerinden kurulur. En kritik kural, cluster atamasinin tarihsel olarak sabitlenmesidir:

- Her walk-forward step basinda yalniz o ana kadar bilinen veri kullanilir
- Test penceresi boyunca cluster assignment dondurulur
- Gelecek volatilite rejimi ile gecmis skor yeniden yazilmaz

Cluster fallback kurallari:

- Bucket boyutu `min_cluster_size` altina duserse once komsu volatilite bucket ile birlesir
- Hala yetersizse `sector-only` fallback aktif olur
- Normalizasyon modu cluster boyutuna gore degisir:
  - `n >= 30`: winsorized z-score
  - `n < 30`: percentile rank normalization

Bu mantik [clustering.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/clustering.py) ve [normalization.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/normalization.py) icinde uygulanir.

## Data & Storage

Veri modeli uc katmanda dusunulmustur:

1. Market data
- `symbols`
- `bars_1d`
- `bars_1h`

2. Research state
- `strategy_definitions`
- `strategy_runs`
- `strategy_scores`
- `setup_candidates`

3. Portfolio state
- `portfolio_positions`
- `job_runs`

PostgreSQL partitioning detayi [schema.sql](/home/mitat/Documents/projects/bistbot/src/bistbot/storage/sql/schema.sql) icindedir. `strategy_runs` ve `strategy_scores` tablolarinda `as_of_date` uzerinden range partitioning kullanilir. Temel indexler:

- `(cluster_id, as_of_date desc)`
- `(strategy_id, as_of_date desc)`

Corporate action uyumlulugu icin `portfolio_positions` tablosunda su alanlar bulunur:

- `adjustment_factor`
- `adjusted_entry_price`
- `adjusted_stop_price`
- `adjusted_target_price`
- `last_corporate_action_at`

## Strategy Engine

Strateji tanimi sadece indikator kombinasyonu degildir; ayni zamanda davranis ailesi tasir:

- `trend_following`
- `pullback_mean_reversion`
- `breakout_volume`

Backtest motoru:

- `24 ay` lookback
- `60 gun train + 30 gun test`
- `30 gun step`

Yeterlilik kurallari:

- toplam OOS islem `>= 50`
- son 6 pencerenin en az 3 tanesinde islem
- `avg_trade_return >= 2 x estimated_round_trip_cost`

Skorlama:

- metrikler cluster icinde normalize edilir
- final skor = `0.4*Ret_norm + 0.2*WinRate_norm + 0.3*ProfitFactor_norm - 0.1*MaxDrawdown_norm`

Aktif strateji secimi:

- cluster basina `1-3` aktif strateji
- ayni aileden ikinci strateji secilmez
- `pairwise OOS return correlation < 0.75`
- uygun aday yoksa slot bos kalir

Bu akisin ana modulleri:

- [scoring.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/scoring.py)
- [strategy_selection.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/strategy_selection.py)
- [backtest.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/backtest.py)

## Signal Lifecycle

Setup uretimi quality gate ile sinirlanir. Bir adayin aktif setup olabilmesi icin:

- ayni scan cycle icinde skor olarak top `%10`
- `expected_R >= 2.0`
- `confluence_score >= 0.75`

Confluence score bilesenleri:

- daily regime `0.30`
- trend signal `0.25`
- momentum signal `0.20`
- volume confirmation `0.15`
- entry-zone proximity `0.10`

Setup durumlari:

- `active`
- `approved_pending_entry`
- `rejected`
- `expired`
- `invalidated`
- `entered`
- `closed`

Yasam dongusu kurallari:

- `1H` setup icin varsayilan omur `6 saat`
- sure dolarsa `expired`
- daily regime bozulursa `invalidated`
- fiyat entry zone'dan `0.5 ATR` fazla kacarsa `invalidated`
- kullanici onayi sonrasinda bile manuel entry aninda tekrar kontrol yapilir

Bu mantik [setup_lifecycle.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/setup_lifecycle.py) icinde tutulur.

## Risk Engine

Risk motoru trade ve portfoy seviyesinde ayni anda calisir.

Trade-level:

- `%1` risk-based sizing
- `entry - stop` uzerinden adet hesabi

Portfolio-level:

- max `2` hisse / sektor
- max `%40` sektor maruziyeti
- `60 gun correlation > 0.75` ise red
- total portfolio risk exposure `<= %5`

Portfolio risk exposure formulu:

`sum(max(last_price - stop_price, 0) * qty) / portfolio_equity`

Holding logic:

- `1-7 gun` hedef pencere soft limit olarak ele alinir
- 7. gun sonrasinda `daily close > EMA20` ve `EMA20 > EMA50` ise pozisyon korunabilir

Bu alanin ana modulleri:

- [risk.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/risk.py)
- [position_management.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/position_management.py)
- [portfolio_adjustments.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/portfolio_adjustments.py)

## Data Quality

Veri kalite katmani corporate action ile aciklanamayan anormal gap'leri karantinaya alir.

Kurallar:

- buyuk gap tespit edilir
- ayni gun corporate action varsa kabul edilir
- aciklama yoksa sembol quarantine edilir

Ayrica corporate action geldiginde acik pozisyonlar da senkron ayarlanir:

- split/bedelsiz: quantity carpilir, price anchor'lar bolunur
- cash dividend: quantity sabit kalir, adjusted anchor'lar dusurulur, simule nakit bakiyesi artar

Bu akisin kodu:

- [data_quality.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/data_quality.py)
- [portfolio_adjustments.py](/home/mitat/Documents/projects/bistbot/src/bistbot/services/portfolio_adjustments.py)

## APIs

Uygulama bootstrap dosyasi [main.py](/home/mitat/Documents/projects/bistbot/src/bistbot/main.py), API router dosyasi [routes.py](/home/mitat/Documents/projects/bistbot/src/bistbot/api/routes.py).

Sunulan endpointler:

- `GET /api/dashboard/overview`
- `GET /api/setups/top`
- `GET /api/setups/{id}`
- `POST /api/setups/{id}/approve`
- `POST /api/setups/{id}/reject`
- `POST /api/positions/manual-entry`
- `PATCH /api/positions/{id}`
- `GET /api/positions`
- `GET /api/backtests/clusters`
- `GET /api/backtests/clusters/{cluster_id}/strategies`
- `GET /api/backtests/strategies/{strategy_id}/trades`
- `POST /api/jobs/{job_name}/run`

V1 veri akisi icin runtime store olarak [memory.py](/home/mitat/Documents/projects/bistbot/src/bistbot/storage/memory.py) kullanilir. Bu katman demo seed verisi ile uygulamayi ayaga kaldirir ve daha sonra DB-backed repository ile degistirilebilir.

## Testing

Test coverage hedefleri:

- PIT cluster assignment
- normalization mode switch
- family diversity + correlation based strategy selection
- dynamic cost behavior
- setup expiration / invalidation / manual-entry revalidation
- data quality quarantine
- corporate action position adjustment
- position sizing ve portfolio risk cap
- API smoke flow

Testler `pytest` ile [tests](/home/mitat/Documents/projects/bistbot/tests) altinda yer alir.
