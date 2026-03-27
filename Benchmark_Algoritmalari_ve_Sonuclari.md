# Benchmark Algoritmalari ve Sonuclari

Bu belge, BISTBot icindeki benchmark/backtest akisini, strateji algoritmalarini ve testlerde dogrulanan ornek sonuclari tek yerde toplar. Icerik, dokumandaki hedef tasarimdan ziyade mevcut calisan implementasyona gore hazirlanmistir.

Tarih: 2026-03-26

## 1. Ust Duzey Akis

Sistemdeki benchmark mantigi su sirayla calisir:

1. Piyasa verisi alinir ve sembol bazli bar serileri hazirlanir.
2. Her sembol icin indikatorler hesaplanir.
3. Semboller sektor ve volatiliteye gore cluster'lara ayrilir.
4. Her cluster icin 3 strateji ailesi calistirilir.
5. Uretilen trade'ler `StrategyScore` metriklerine ozetlenir.
6. Skorlar cluster icinde normalize edilir.
7. Composite skor hesaplanir.
8. Korelasyon ve aile cesitliligi filtresinden gecen aktif stratejiler secilir.
9. Bu aktif stratejilerden setup adaylari uretilir ve quality gate uygulanir.

## 2. Kullanilan Ana Algoritmalar

### 2.1 Cluster ve benchmark temeli

- Cluster mantigi sektor + volatilite bucket uzerine kurulu.
- Volatilite referansi `ATR60%` mantigi ile turetiliyor.
- Cluster ici karsilastirma kullaniliyor; yani stratejiler tum evrende degil, ayni cluster icinde yaristiriliyor.

Bu kisim agirlikli olarak su dosyalarda:

- `src/bistbot/services/clustering.py`
- `src/bistbot/services/research.py`
- `src/bistbot/services/normalization.py`

### 2.2 Hesaplanan indikatorler

`compute_indicators()` su indikatorleri uretir:

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

Bu indikatorler strateji sinyali, stop mantigi ve setup confidence hesaplarinda kullanilir.

### 2.3 Strateji aileleri

Sistemde 3 strateji ailesi vardir:

#### Trend Following

Giris mantigi:

- Fiyat `EMA20 > EMA50` yapisinin ustunde olmali.
- `RSI > 55` olmali.
- `MACD line > MACD signal` olmali.
- Hacim onayi icin `volume_ratio20 > 1.0` olmali.

Cikis mantigi:

- `+1R` gorulurse stop break-even'a cekilir.
- Trend gucluyken pozisyon `highest close - 2.5 * ATR14` trailing stop ile tasinir.
- Daha derin trend kirilimi olarak fiyat `EMA50` altina inerse cikis.

#### Pullback Mean Reversion

Giris mantigi:

- Fiyat `EMA50` uzerinde kalmali.
- Onceki kapanis `EMA20` altindayken yeni kapanis tekrar `EMA20` ustune donmeli.
- `RSI`, `45` seviyesini asagi yukari kesmeli.
- Hacim onayi icin `volume_ratio20 > 0.9` olmali.

Cikis mantigi:

- `2R` hedefe ulasirsa cikis.
- 10 bar tutulduysa cikis.
- Fiyat `EMA50` altina inerse cikis.

#### Breakout Volume

Giris mantigi:

- Fiyat `EMA20` ustunde olmali.
- Fiyat onceki `20` bar zirvesini asmali.
- `ROC10 > 0` olmali.
- Hacim onayi icin `volume_ratio20 > 1.3` olmali.

Cikis mantigi:

- `2R` hedefe ulasirsa cikis.
- 12 bar tutulduysa cikis.
- Fiyat `EMA20` altina inerse cikis.

### 2.4 Pozisyon ve risk davranisi

Trade acildiginda:

- Giris fiyati kapanistan alinir.
- Baslangic riski `ATR14 * 1.5` olarak kurulur.
- Stop ilk anda `entry - risk` seviyesindedir.

Trade acikken:

- Trend stratejisinde fiyat `+1R` gorurse stop break-even'a cekilir ve sonra ATR bazli trailing stop devreye girer.
- Mean reversion ve breakout stratejilerinde fiyat `+1R` gorurse stop break-even'a cekilir.
- Mean reversion ve breakout stratejilerinde fiyat `+2R` gorurse stop `+1R` seviyesine cekilir.
- Stop once tetiklenirse cikis stop fiyatindan yazilir.

### 2.5 Sonuc metrikleri nasil uretiliyor

Her strateji icin su metrikler hesaplanir:

- `total_return`
- `win_rate`
- `profit_factor`
- `max_drawdown`
- `trade_count`
- `avg_trade_return`
- `estimated_round_trip_cost`
- son 6 pencere icin `oos_window_trade_counts`
- son 6 pencere icin `oos_returns`

Ozetleme mantiginda dikkat ceken noktalar:

- Trade'ler once sembol bazinda gruplanir.
- Her sembol icin equity curve uretilir.
- `max_drawdown`, semboller arasi `75. persentil` ile alinir.
- Son 6 pencere, 30 gunluk dilimler halinde toplanir.

Bu tasarim, tek bir sembolun asiri iyi veya asiri kotu sonucunun cluster skorunu tek basina bozmasini azaltir.

### 2.6 Normalizasyon algoritmasi

Cluster icindeki stratejiler iki farkli yolla normalize edilir:

- `n < 30` ise `percentile rank normalization`
- `n >= 30` ise `winsorized z-score`

Normalize edilen alanlar:

- toplam getiri
- kazanma orani
- profit factor
- max drawdown

### 2.7 Composite score formulu

Mevcut kodda composite skorun ana govdesi su formulle hesaplanir:

`0.4 * normalized_return + 0.2 * normalized_win_rate + 0.3 * normalized_profit_factor - 0.18 * normalized_max_drawdown`

Ek drawdown mantigi:

- `max_drawdown > 0.20` olduktan sonra ek bir yumusak ceza daha uygulanir.
- `max_drawdown > 0.30` ise strateji `garbage` sayilir.
- Bu noktadan sonra composite skor `-inf` olur.

Not:

- `Mimari.md` icinde drawdown cezasi `0.10` gibi gorunuyor.
- Mevcut implementasyonda calisan normalize drawdown agirligi `0.18` dir ve buna ek yumusak raw-DD cezasi vardir.

### 2.8 Aktif strateji secimi

`select_active_strategies()` fonksiyonu, sadece composite skora bakmaz. Ek koruma katmanlari vardir:

- `trade_count >= 12`
- Son 6 pencerenin en az 2 tanesinde islem olmali.
- `avg_trade_return >= 1.25 * estimated_round_trip_cost`
- `max_drawdown <= 0.30`
- Ayni aileden ikinci strateji alinmaz.
- Secilen stratejiler arasinda `pairwise OOS return correlation < 0.75` olmali.
- Varsayilan olarak cluster basina en fazla 3 aktif strateji secilir.

Not:

- `Mimari.md` icinde daha sert esikler anlatiliyor.
- Mevcut kod daha yumusak esiklerle calisiyor.

### 2.9 Setup quality gate

Aktif stratejilerden setup adaylari cikarildiktan sonra ikinci bir kalite filtresi vardir.

`compute_confluence_score()` su agirliklari kullanir:

- daily regime: `0.30`
- trend signal: `0.25`
- momentum signal: `0.20`
- volume confirmation: `0.15`
- entry zone proximity: `0.10`

`quality_gate()` icin adayin:

- son `6` bar icinde sinyal vermis olmasi aranir
- `expected_r >= 1.5`
- `confluence_score >= 0.65`

kosullarini saglamasi gerekir. Sonrasinda adaylar skora gore siralanir; runtime ayarinda varsayilan olarak en ust `%20` tutulur ve mumkunse en az `3` setup birakilir.

## 3. Testlerde Gorulen Ornek Sonuclar

Asagidaki maddeler, test dosyalarinda dogrudan dogrulanan davranislardir.

### 3.1 Normalizasyon sonuclari

- Kucuk cluster senaryosunda 3 stratejinin getirileri `0.10`, `0.20`, `0.30` oldugunda normalize getiri sonucu `0.0`, `0.5`, `1.0` oluyor.
- 30 elemanli buyuk cluster senaryosunda en dusuk getiri negatif z-score, en yuksek getiri pozitif z-score aliyor.

Yorum:

- Az sayidaki adayda siralama odakli bir benchmark kullaniliyor.
- Buyuk cluster'da dagilim farklari daha anlamli sekilde ayristiriliyor.

### 3.2 Composite score sonuclari

- Tum normalize alanlar `1.0` iken ve `max_drawdown = 0.12` oldugunda composite skor `0.72` cikiyor.
- `max_drawdown = 0.25` oldugunda skor hala sonlu kaliyor ve `0.42` seviyesine iniyor.
- `max_drawdown = 0.31` oldugunda skor `-inf` oluyor.

Yorum:

- Sistem drawdown'a halen ceza uyguluyor ama `%20-%30` bandinda artik tam kara liste yerine yumusak bastirma kullaniyor.
- Asiri drawdown yapan stratejiler ise `%30` sonrasinda yine benchmark disina itiliyor.

### 3.3 Strateji secimi sonuclari

Ornek testte secilen stratejiler sunlar:

- `trend-a`
- `pullback-a`
- `breakout-diversified`

Secilmeyenler:

- `breakout-high-corr`: korelasyon cok yuksek oldugu icin eleniyor.
- `trend-high-dd`: drawdown `%31` oldugu icin eleniyor.

Yorum:

- Sistem sadece "en yuksek skoru" almaz.
- Cesitlilik ve korelasyon filtresi, ayni davranisi tekrar eden stratejileri disarida birakir.

### 3.4 Backtest trade uretimi

Breakout stratejisi icin kurulan test verisinde sistem en az 1 trade uretiyor. Ilk trade icin su durumlar testte dogrulaniyor:

- entry price var
- exit price var
- entry zamani exit zamanindan once

Yorum:

- Sinyal, trade acma ve trade kapama zinciri pratikte calisiyor.

### 3.5 Setup quality gate sonuclari

- 20 setup adayli testte quality gate sadece en ust 2 adayi birakiyor.
- `min_keep=3` verildiginde ayni havuzdan ilk 3 aday korunabiliyor.
- Tum bilesenler olumluysa confluence score `1.0` oluyor.
- Onaylanan setup manuel entry oncesi tekrar validasyondan geciyor.

Yorum:

- Sistem benchmark sonrasinda bir de setup kalitesi icin ikinci eleme kati kullaniyor.

## 4. Pratik Sonuc Ozeti

Mevcut implementasyona gore sistemin davranisi su sekilde ozetlenebilir:

- Dusuk drawdown, yuksek getiriden neredeyse daha onemli hale gelmis durumda.
- Cluster ici normalizasyon sayesinde farkli sektor ve volatilite rejimleri birbirine dogrudan karistirilmiyor.
- Ayni aileden fazla strateji secilmemesi, portfoyde davranis cesitliligi sagliyor.
- OOS pencere aktivitesi ve maliyet filtresi, sadece kagit uzerinde iyi gorunen stratejileri ayiklamaya yardim ediyor.
- Setup quality gate, benchmark kazananlarin bile hepsini aktif fikir haline getirmiyor.

## 5. Kod Referanslari

Bu belgedeki algoritmalarin ana kaynaklari:

- `src/bistbot/services/research.py`
- `src/bistbot/services/normalization.py`
- `src/bistbot/services/scoring.py`
- `src/bistbot/services/strategy_selection.py`
- `src/bistbot/services/setup_lifecycle.py`
- `tests/test_research.py`
- `tests/test_normalization.py`
- `tests/test_scoring.py`
- `tests/test_strategy_selection.py`
- `tests/test_setup_lifecycle.py`

## 6. Operasyonel Not

`bistbot.log` icinde Yahoo 1 saatlik veri icin "requested range must be within the last 730 days" uyarisinin tekrarlandigi goruluyor. Bu, uzun lookback ile saatlik veri cekilen senaryolarda benchmark kapsamini azaltabilir.

## 7. Gercek Hisse Sonuclari

Bu bolum, local cache icindeki gercek arastirma snapshot'ina gore hazirlandi.

Not:

- Kod seviyesindeki son exit/DD/gate degisikliklerinden sonra bu snapshot henuz yeniden refresh edilmedi.
- Asagidaki gercek hisse sonuclari bir onceki cache durumunu temsil eder.

- Kaynak: `.cache/bistbot/research_state.json`
- Cache zamani: `2026-03-26 14:13 UTC` / `2026-03-26 17:13 TRT`
- Timeframe: `4h`
- Cluster sayisi: `33`
- Strateji sayisi: `99`
- Backtest ozeti uretilen hisse sayisi: `513`
- Aktif setup sayisi: `1`

Onemli yorum:

- Asagidaki hisse getirileri, o hisse uzerindeki gorunur backtest trade'lerinin bilesik sonucudur.
- Bu rakamlar tek bir stratejinin ya da portfoy kisiti uygulanmis canli portfoyun birebir getirisi gibi okunmamalidir.
- `strategy_count`, ilgili hissede kac farkli stratejinin trade urettigini gosterir.

### 7.1 Daha saglam gorunen en iyi hisseler

Asagidaki tablo, en az `20` trade ureten hisseler icinden alinmistir.

| Hisse | Sektor | Trade | Strateji | Toplam Getiri % | Win Rate % | Avg R | Son Trade |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| SKBNK | banking | 50 | 3 | 229.21 | 50.00 | 0.84 | 2026-03-02 |
| TUREX | transportation | 32 | 2 | 205.55 | 62.50 | 1.03 | 2026-03-19 |
| BMSTL | basic_materials | 37 | 2 | 136.70 | 54.05 | 0.72 | 2026-02-13 |
| TMPOL | basic_materials | 27 | 2 | 130.17 | 51.85 | 0.65 | 2026-03-16 |
| ESEN | utilities | 30 | 2 | 128.01 | 63.33 | 0.62 | 2026-03-25 |
| CEMZY | consumer_defensive | 31 | 2 | 107.93 | 54.84 | 0.53 | 2026-03-25 |
| ECILC | healthcare | 34 | 2 | 100.41 | 52.94 | 0.61 | 2026-03-25 |
| TUPRS | energy | 41 | 3 | 89.76 | 48.78 | 0.61 | 2026-03-25 |
| GUNDG | consumer_defensive | 22 | 2 | 83.12 | 59.09 | 0.45 | 2026-02-20 |
| ALBRK | banking | 45 | 3 | 78.38 | 44.44 | 0.35 | 2026-02-19 |

Kisa okuma:

- Bankacilik ve basic materials tarafinda guclu isimler one cikiyor.
- `SKBNK` ve `TUREX`, hem yuksek toplam getiri hem de makul trade sayisi ile dikkat cekiyor.
- `TUPRS`, daha tanidik bir buyuk hisse olarak ilk 10 icinde yer aliyor.

### 7.2 Daha zayif kalan hisseler

Asagidaki tablo da en az `20` trade filtresi ile alinmistir.

| Hisse | Sektor | Trade | Strateji | Toplam Getiri % | Win Rate % | Avg R | Son Trade |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| ACSEL | basic_materials | 29 | 2 | -43.09 | 20.69 | -0.42 | 2026-03-26 |
| CANTE | utilities | 27 | 2 | -33.68 | 22.22 | -0.29 | 2026-03-25 |
| ICBCT | banking | 38 | 3 | -32.29 | 21.05 | -0.21 | 2026-03-18 |
| RAYSG | insurance | 24 | 2 | -28.89 | 29.17 | -0.30 | 2026-02-26 |
| ANGEN | healthcare | 27 | 2 | -27.31 | 29.63 | -0.26 | 2026-02-24 |
| TLMAN | transportation | 32 | 2 | -25.49 | 31.25 | -0.17 | 2026-02-18 |
| AYDEM | utilities | 27 | 2 | -25.26 | 22.22 | -0.27 | 2026-03-11 |
| TSKB | banking | 49 | 3 | -24.44 | 26.53 | -0.21 | 2026-02-19 |
| ANSGR | insurance | 27 | 2 | -20.24 | 25.93 | -0.16 | 2026-03-16 |
| TRCAS | utilities | 52 | 3 | -19.71 | 30.77 | 0.07 | 2026-03-02 |

Kisa okuma:

- Utilities ve banking tarafinda kazananlar oldugu gibi belirgin kaybedenler de var.
- Bu durum, sistemin sektor secmekten cok hisse ve setup kalitesine duyarliligini gosteriyor.

### 7.3 En guclu aktif stratejiler

Asagidaki stratejiler, hem aktif secilenler arasinda hem de composite score olarak ust siralarda yer aliyor.

| Strateji | Cluster | Aile | Getiri % | Win Rate % | Profit Factor | Max DD % | Trade | Composite |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| technology:mid:pullback_mean_reversion | technology:mid | pullback_mean_reversion | 7.62 | 38.10 | 1.77 | 9.82 | 63 | 0.90 |
| technology:high:pullback_mean_reversion | technology:high | pullback_mean_reversion | 4.77 | 31.71 | 1.55 | 7.03 | 41 | 0.80 |
| basic_materials:high:breakout_volume | basic_materials:high | breakout_volume | 31.36 | 43.82 | 1.62 | 18.70 | 445 | 0.75 |
| unknown:all:pullback_mean_reversion | unknown:all | pullback_mean_reversion | 14.04 | 45.00 | 2.17 | 13.80 | 20 | 0.70 |
| banking:mid:pullback_mean_reversion | banking:mid | pullback_mean_reversion | 5.83 | 47.17 | 1.96 | 5.68 | 53 | 0.50 |
| banking:mid:breakout_volume | banking:mid | breakout_volume | 19.00 | 39.33 | 1.63 | 13.59 | 239 | 0.50 |
| utilities:low:breakout_volume | utilities:low | breakout_volume | 12.96 | 41.38 | 1.28 | 18.43 | 174 | 0.40 |
| consumer_defensive:high:breakout_volume | consumer_defensive:high | breakout_volume | 23.47 | 41.36 | 1.56 | 19.40 | 324 | 0.40 |

Kisa okuma:

- Teknoloji cluster'larinda `pullback_mean_reversion` ailesi cok guclu gorunuyor.
- Yuksek trade sayisi ile dikkat ceken en guclu aktif strateji `basic_materials:high:breakout_volume`.

### 7.4 Mevcut aktif setup

Cache snapshot'inda yalnizca 1 aktif setup gorunuyor:

| Hisse | Cluster | Strateji | Aile | Score | Confidence | Durum |
| --- | --- | --- | --- | ---: | ---: | --- |
| CVKMD | basic_materials:high | basic_materials:high:breakout_volume | breakout_volume | 1.6648 | 0.8702 | active |

Yorum:

- Sistem cok sayida backtest sonucu uretse de quality gate sonunda yalnizca cok sinirli sayida setup birakiyor.
- Su anki snapshot'ta benchmark ve filtrelerden gecen tek aktif fikir `CVKMD`.
