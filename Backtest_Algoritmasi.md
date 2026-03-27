# Backtest Algoritmasi

Bu belge, BISTBot icindeki backtest mantiginin mevcut implementasyonda nasil calistigini anlatir.
Odak noktasi hedef mimari degil, bugun kodda calisan akistir.

Tarih: 2026-03-27

## 1. Kisa Ozet

Sistem su sirayla calisir:

1. Sembol ve sektor listesi provider'dan alinir.
2. Her sembol icin zaman serisi indirilir.
3. Her seride teknik indikatorler hesaplanir.
4. Semboller sektor + volatiliteye gore cluster'lara ayrilir.
5. Her cluster icin 3 strateji ailesi tum lookback boyunca simule edilir.
6. Uretilen trade'lerden strateji skorlari hesaplanir.
7. Skorlar cluster icinde normalize edilir ve composite skor uretilir.
8. Guard kurallarini gecen, aile cesitliligi ve dusuk korelasyon saglayan aktif stratejiler secilir.
9. Aktif stratejilerden guncel setup adaylari uretilir.

Ana implementasyon: `src/bistbot/services/research.py`

## 2. Gercek Veri Akisi

Backtest akisi `build_real_research_state()` ile baslar.

Varsayilan ayarlar:

- `research_timeframe = "4h"`
- `backtest_lookback_days = 730`
- `4h` modunda efektif lookback en fazla `720` gun
- `backtest_min_daily_bars = 240`
- `min_cluster_size = 8`

Akis:

1. `provider.fetch_sectors()` ile sektorler alinir.
2. `provider.fetch_symbols()` ile semboller alinir.
3. Her sembol icin `provider.fetch_bars()` cagrilir.
4. Bar sayisi yetersiz olan semboller elenir.
5. Kalan semboller icin indikatorler hesaplanir.
6. `ATR60%` degeri olan semboller clustering'e gonderilir.

Kullanim noktasi:

- `src/bistbot/services/research.py`
- `src/bistbot/config.py`

## 3. Indikator Hesaplari

`compute_indicators()` su serileri uretir:

- `EMA20`
- `EMA50`
- `RSI14`
- `ATR14`
- `ATR14%`
- `ATR60%`
- `Volume Ratio 20`
- `ROC10`
- `MACD line`
- `MACD signal`
- `20 bar breakout high`

Bu indikatorler hem signal ureterek trade acmakta hem de stop/exit mantiginda kullanilir.

## 4. Cluster Algoritmasi

Cluster mantigi `sector x volatility bucket` uzerine kuruludur.

Volatilite:

- Her sembol icin `ATR60%` kullanilir.

Gruplama:

- Ayni sektordeki semboller birlikte ele alinir.
- Her sektor kendi icinde `low`, `mid`, `high` volatilite bucket'larina ayrilir.
- Ayirim, ATR60% siralamasina gore yaklasik tercile mantigi ile yapilir.

Fallback kurallari:

- Bir bucket `min_cluster_size` altinda kalirsa once komsu bucket ile birlestirilir.
- Hala yetersizse o sektor tek bir `sector:all` cluster'ina dusurulur.

Kod:

- `src/bistbot/services/clustering.py`

## 5. Strateji Aileleri

Sistemde 3 strateji ailesi vardir:

1. `trend_following`
2. `pullback_mean_reversion`
3. `breakout_volume`

Her cluster icin bu 3 ailenin her biri ayri bir `strategy_id` ile calistirilir.

Ornek:

```text
banking:low:trend_following
banking:low:pullback_mean_reversion
banking:low:breakout_volume
```

## 6. Giris Kurallari

### 6.1 Trend Following

Signal aktif olur eger:

- `close > EMA20 > EMA50`
- `RSI14 > 55`
- `MACD line > MACD signal`
- `volume_ratio20 > 1.0`

### 6.2 Pullback Mean Reversion

Signal aktif olur eger:

- `close > EMA50`
- onceki kapanis `EMA20` altindayken yeni kapanis `EMA20` ustune donmusse
- `RSI14` once `45` altindayken sonra `45` ustune gecmisse
- `volume_ratio20 > 0.9`

### 6.3 Breakout Volume

Signal aktif olur eger:

- `close > EMA20`
- `close > previous_20_bar_high`
- `ROC10 > 0`
- `volume_ratio20 > 1.3`

Kod:

- `signal_components()`
- `strategy_signal()`

## 7. Trade Simulasyonu

Trade simulasyonu `simulate_strategy()` icinde yapilir.

Genel kurallar:

- Dongu `index = 60` sonrasinda baslar.
- Ayni anda tek pozisyon varsayilir.
- Giris fiyati sinyal gelen barin `close` degeridir.
- `ATR14` yoksa trade acilmaz.
- Baslangic risk mesafesi `ATR14 * 1.5` tir.
- Ilk stop `entry_price - risk` tir.

Pozisyon acildiktan sonra her yeni barda:

1. `bars_held` artirilir.
2. Stop vurulmus mu diye `bar.low <= stop` kontrol edilir.
3. Gerekirse stop yukari tasinir.
4. Stratejiye gore exit kosulu calistirilir.

### 7.1 Stop Guncelleme

Trend following:

- Fiyat `+1R` gorurse stop en az break-even'a cekilir.
- Sonra trailing stop: `highest_close - 2.5 * ATR14`

Pullback ve breakout:

- Fiyat `+1R` gorurse stop break-even'a cekilir.
- Fiyat `+2R` gorurse stop en az `entry + 1R` olur.

### 7.2 Exit Kurallari

Trend following:

- `close < EMA50`

Pullback mean reversion:

- `high >= entry + 2R`
- veya `bars_held >= 10`
- veya `close < EMA50`

Breakout volume:

- `high >= entry + 2R`
- veya `bars_held >= 12`
- veya `close < EMA20`

Trade kaydi:

- `return_pct = (exit - entry) / entry`
- `r_multiple = (exit - entry) / risk`

## 8. Skor Uretimi

Her strateji icin tum trade'ler `summarize_strategy()` ile ozetlenir.

Hesaplanan ana metrikler:

- `total_return`
- `win_rate`
- `profit_factor`
- `max_drawdown`
- `trade_count`
- `avg_trade_return`
- `estimated_round_trip_cost`
- `oos_window_trade_counts`
- `oos_returns`

Onemli detay:

- Trade'ler once sembol bazinda gruplanir.
- Her sembol icin ayri equity curve uretilir.
- `max_drawdown`, sembol bazli drawdown'larin `75. persentil`i olarak alinir.
- Son 6 pencere, son 180 gunu temsil eden `6 x 30 gun` bloklar halinde hesaplanir.

Bu nedenle mevcut sistemde strateji skoru tek bir sembolun sonucuna degil, cluster icindeki sembol dagilimina daha dengeli bakar.

## 9. Maliyet Hesabi

`estimated_round_trip_cost()` su bilesenleri toplar:

- broker fee
- taxes
- base slippage
- volatility-adjusted slippage

Volatilite duzeltilmis slippage mantigi:

- baseline olarak `ATR20_60d_median` kullanilir
- yoksa `ATR20_current` kullanilir
- slippage carpani `max(1.0, current / baseline)` seklindedir

## 10. Normalizasyon ve Composite Skor

Cluster icinde normalizasyon:

- `n >= 30` ise `winsorized z-score`
- `n < 30` ise `percentile rank`

Normalize edilen alanlar:

- total return
- win rate
- profit factor
- max drawdown

Composite skor formulu:

```text
0.4 * normalized_return
+ 0.2 * normalized_win_rate
+ 0.3 * normalized_profit_factor
- 0.18 * normalized_max_drawdown
- excess_drawdown_penalty(max_drawdown)
```

Drawdown kurallari:

- `max_drawdown > 0.20` ise ek yumusak ceza baslar
- `max_drawdown > 0.30` ise strateji `garbage` sayilir
- bu durumda skor `-inf` olur

Kod:

- `src/bistbot/services/normalization.py`
- `src/bistbot/services/scoring.py`

## 11. Aktif Strateji Secimi

Her cluster icinde butun stratejiler aktif sayilmaz.
`select_active_strategies()` once guard uygular, sonra cesitlilik filtresi ekler.

Guard kosullari:

- `trade_count >= 12`
- son 6 pencerenin en az 2 tanesinde islem olmali
- `avg_trade_return >= 1.25 * estimated_round_trip_cost`
- `max_drawdown <= 0.30`

Cesitlilik kurallari:

- aile onceligi: trend, pullback, breakout
- ayni aileden ikinci strateji alinmaz
- secilen stratejiler arasinda `pairwise OOS return correlation < 0.75` olmali
- varsayilan `max_active = 3`

Kod:

- `src/bistbot/services/strategy_selection.py`

## 12. Setup Uretimi

Backtest'in son ciktisi sadece skor degildir; ayni zamanda canliya yakin setup adaylari da uretilir.

Akis:

1. Yalnizca aktif secilen stratejiler ele alinir.
2. Cluster icindeki semboller tekrar taranir.
3. Son `lookback_bars` icinde signal var mi diye bakilir.
4. Signal bulunduysa entry zone, stop, target ve confidence hesaplanir.

Varsayilanlar:

- `setup_signal_lookback_bars = 6`
- `setup_min_expected_r = 1.5`
- `setup_min_confluence_score = 0.65`
- `quality_gate_percentile = 0.20`
- `quality_gate_min_keep = 3`

Confluence formulu:

```text
0.30 * daily_regime_valid
+ 0.25 * trend_signal
+ 0.20 * momentum_signal
+ 0.15 * volume_confirmation
+ 0.10 * entry_zone_proximity
```

Risk ve hedef mantigi:

- `entry_low = last_close - 0.25 * ATR14`
- `entry_high = last_close + 0.25 * ATR14`
- `stop = last_close - 1.5 * ATR14`
- `target = last_close + 3.0 * ATR14`
- `expected_r = (target - entry_high) / (entry_high - stop)`
- `confidence = min(0.99, 0.55 + 0.35 * confluence)`

Sonra `quality_gate()` su filtreyi uygular:

- `expected_r >= min_expected_r`
- `confluence_score >= min_confluence_score`
- skor siralamasinda ust dilimde olmak

## 13. Pseudo Kod

```text
build_real_research_state():
    symbols = provider.fetch_symbols()
    sectors = provider.fetch_sectors()

    for symbol in symbols:
        bars = provider.fetch_bars(symbol)
        if bars yetersiz:
            continue
        indicators = compute_indicators(bars)
        snapshot = ATR60% ile olustur

    clusters = assign_point_in_time_clusters(snapshots)

    for cluster in clusters:
        for family in [trend, pullback, breakout]:
            trades = []
            for symbol in cluster.members:
                trades += simulate_strategy(family, symbol, bars, indicators)
            score = summarize_strategy(trades)
            cluster_scores += score

    normalized_scores = score_clusters(cluster_scores)
    active = select_active_strategies(normalized_scores)
    setups = build_setup_candidates(active)
    return result
```

## 14. Walk-Forward Hakkinda Duz Not

Kod tabaninda `src/bistbot/services/backtest.py` icinde `generate_walk_forward_windows()` fonksiyonu var.
Bu fonksiyon `60 gun train + 30 gun test + 30 gun step` pencereleri uretebiliyor.

Ama bugunku implementasyonda bu pencere ureticisi arastirma pipeline'ina bagli degil.
Yani su an calisan gercek backtest:

- tam lookback boyunca tek-pass trade simulasyonu
- uzerine son 6 adet 30 gunluk pencere ile OOS-benzeri ozetleme

Dolayisiyla belgede anlatilan algoritma "mevcut calisan sistem"dir; tam walk-forward motoru henuz aktif degildir.

## 15. Ilgili Dosyalar

- `src/bistbot/services/research.py`
- `src/bistbot/services/clustering.py`
- `src/bistbot/services/normalization.py`
- `src/bistbot/services/scoring.py`
- `src/bistbot/services/strategy_selection.py`
- `src/bistbot/services/setup_lifecycle.py`
- `src/bistbot/services/costs.py`
- `src/bistbot/services/backtest.py`
- `Benchmark_Algoritmalari_ve_Sonuclari.md`
