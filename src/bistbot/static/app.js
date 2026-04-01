function setLoadingVisible(visible, message = '') {
  const overlay = document.querySelector('[data-loading-overlay]');
  if (!overlay) {
    return;
  }
  if (message) {
    const messageNode = overlay.querySelector('[data-loading-message]');
    if (messageNode) {
      messageNode.textContent = message;
    }
  }
  overlay.classList.toggle('is-hidden', !visible);
}

function setLoadingProgress(percent, message = '') {
  const percentNode = document.querySelector('[data-loading-percent]');
  const barNode = document.querySelector('[data-loading-progress-bar]');
  if (percentNode) {
    percentNode.textContent = `%${Math.max(0, Math.min(100, Math.round(percent)))}`;
  }
  if (barNode) {
    barNode.style.width = `${Math.max(0, Math.min(100, Math.round(percent)))}%`;
  }
  if (message) {
    const messageNode = document.querySelector('[data-loading-message]');
    if (messageNode) {
      messageNode.textContent = message;
    }
  }
}

let chartLibraryPromise = null;

async function ensureChartLibrary() {
  if (window.LightweightCharts) {
    return true;
  }
  if (chartLibraryPromise) {
    return chartLibraryPromise;
  }

  const sources = [
    'https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js',
    'https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js',
  ];

  chartLibraryPromise = (async () => {
    for (const source of sources) {
      const loaded = await loadScript(source);
      if (loaded && window.LightweightCharts) {
        return true;
      }
    }
    return false;
  })();

  return chartLibraryPromise;
}

function loadScript(source) {
  return new Promise((resolve) => {
    const existing = document.querySelector(`script[data-chart-lib="${source}"]`);
    if (existing) {
      existing.addEventListener('load', () => resolve(true), { once: true });
      existing.addEventListener('error', () => resolve(false), { once: true });
      window.setTimeout(() => resolve(Boolean(window.LightweightCharts)), 2500);
      return;
    }

    const script = document.createElement('script');
    script.src = source;
    script.async = true;
    script.dataset.chartLib = source;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
    window.setTimeout(() => resolve(Boolean(window.LightweightCharts)), 2500);
  });
}

function destroyChart(container) {
  if (container._chartCleanup) {
    container._chartCleanup();
    container._chartCleanup = null;
  }
  container.innerHTML = '';
}

function createTradingStyleChart(container, payload) {
  destroyChart(container);

  if (!window.LightweightCharts) {
    container.innerHTML = '<div class="chart-empty">Grafik kutuphanesi yuklenemedi.</div>';
    return;
  }

  const chart = window.LightweightCharts.createChart(container, {
    autoSize: true,
    height: 340,
    layout: {
      background: { color: '#fff9f0' },
      textColor: '#5f6a77',
      fontFamily: '"Trebuchet MS", "Verdana", sans-serif',
    },
    grid: {
      vertLines: { color: 'rgba(29, 36, 48, 0.06)' },
      horzLines: { color: 'rgba(29, 36, 48, 0.06)' },
    },
    rightPriceScale: {
      borderColor: 'rgba(29, 36, 48, 0.14)',
    },
    timeScale: {
      borderColor: 'rgba(29, 36, 48, 0.14)',
      timeVisible: true,
      secondsVisible: false,
    },
    crosshair: {
      mode: window.LightweightCharts.CrosshairMode.Normal,
    },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: '#0d8a76',
    downColor: '#d26d3d',
    borderVisible: false,
    wickUpColor: '#0d8a76',
    wickDownColor: '#d26d3d',
    priceLineVisible: false,
    lastValueVisible: true,
  });

  candleSeries.setData(payload.candles || []);
  if (payload.markers && payload.markers.length > 0) {
    candleSeries.setMarkers(payload.markers);
  }

  (payload.price_lines || []).forEach((line) => {
    candleSeries.createPriceLine({
      price: line.price,
      color: line.color,
      lineWidth: line.lineWidth || 2,
      axisLabelVisible: true,
      title: line.title,
    });
  });

  chart.timeScale().fitContent();

  const resizeObserver = new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
  });
  resizeObserver.observe(container);
  container._chartCleanup = () => {
    resizeObserver.disconnect();
    chart.remove();
  };
}

function renderPayloadIntoContainer(container, payload) {
  if (!payload.candles || payload.candles.length === 0) {
    destroyChart(container);
    container.innerHTML = '<div class="chart-empty">Gosterilecek mum verisi yok.</div>';
    return;
  }
  createTradingStyleChart(container, payload);
}

function renderStaticCharts() {
  document.querySelectorAll('.chart-card').forEach((card) => {
    if (card.dataset.dynamicChart === 'true') {
      return;
    }
    const container = card.querySelector('.tv-chart');
    const payloadNode = card.querySelector('.chart-payload');
    if (!container || !payloadNode) {
      return;
    }
    try {
      const payload = JSON.parse(payloadNode.textContent);
      renderPayloadIntoContainer(container, payload);
    } catch (error) {
      destroyChart(container);
      container.innerHTML = '<div class="chart-empty">Grafik olusturulamadi.</div>';
    }
  });
}

async function loadMarketSymbolChart(symbol) {
  const browser = document.querySelector('[data-market-browser]');
  if (!browser) {
    return;
  }

  const trimmedSymbol = (symbol || '').trim().toUpperCase();
  const container = browser.querySelector('[data-market-chart-container]');
  const status = browser.querySelector('[data-market-symbol-status]');
  const title = browser.querySelector('[data-market-chart-title]');
  const subtitle = browser.querySelector('[data-market-chart-subtitle]');
  const meta = browser.querySelector('[data-market-chart-meta]');

  if (!trimmedSymbol) {
    if (status) {
      status.textContent = 'Lutfen once bir sembol sec.';
    }
    return;
  }

  if (status) {
    status.textContent = `${trimmedSymbol} icin grafik yukleniyor...`;
  }
  setLoadingVisible(true, `${trimmedSymbol} icin mum grafigi aliniyor...`);
  setLoadingProgress(20, `${trimmedSymbol} icin mum grafigi aliniyor...`);
  destroyChart(container);
  container.innerHTML = '<div class="chart-empty">Gercek mum verisi getiriliyor...</div>';

  try {
    await ensureChartLibrary();
    const response = await fetch(`/api/market/charts/${encodeURIComponent(trimmedSymbol)}`);
    if (!response.ok) {
      throw new Error('not-found');
    }
    const payload = await response.json();
    renderPayloadIntoContainer(container, payload);
    if (title) {
      title.textContent = payload.title || trimmedSymbol;
    }
    if (subtitle) {
      subtitle.textContent = payload.subtitle || 'Gercek mum verisi';
    }
    if (meta) {
      meta.textContent = `${payload.bar_count || 0} mum · ${payload.data_source || 'Veri kaynagi yok'}`;
    }
    if (status) {
      status.textContent = `${trimmedSymbol} yuklendi. Son fiyat: ${payload.last_price ?? '-'}`;
    }
    setLoadingProgress(100, `${trimmedSymbol} grafigi hazir.`);
  } catch (error) {
    destroyChart(container);
    container.innerHTML = '<div class="chart-empty">Bu sembol icin grafik yuklenemedi.</div>';
    if (status) {
      status.textContent = `${trimmedSymbol} icin veri bulunamadi.`;
    }
    setLoadingProgress(100, `${trimmedSymbol} icin veri bulunamadi.`);
  } finally {
    window.setTimeout(() => {
      setLoadingVisible(false);
    }, 180);
  }
}

async function loadBacktestSymbolChart(symbol) {
  const browser = document.querySelector('[data-backtest-browser]');
  if (!browser) {
    return;
  }

  const trimmedSymbol = (symbol || '').trim().toUpperCase();
  const container = browser.querySelector('[data-backtest-chart-container]');
  const status = browser.querySelector('[data-backtest-symbol-status]');
  const title = browser.querySelector('[data-backtest-chart-title]');
  const subtitle = browser.querySelector('[data-backtest-chart-subtitle]');
  const meta = browser.querySelector('[data-backtest-chart-meta]');

  if (!trimmedSymbol) {
    if (status) {
      status.textContent = 'Lutfen once walk-forward hissesi sec.';
    }
    return;
  }

  if (status) {
    status.textContent = `${trimmedSymbol} walk-forward OOS backtesti yukleniyor...`;
  }
  setLoadingVisible(true, `${trimmedSymbol} icin walk-forward OOS grafigi aliniyor...`);
  setLoadingProgress(20, `${trimmedSymbol} icin walk-forward OOS grafigi aliniyor...`);
  destroyChart(container);
  container.innerHTML = '<div class="chart-empty">Walk-forward OOS grafigi hazirlaniyor...</div>';

  try {
    await ensureChartLibrary();
    const response = await fetch(`/api/backtests/symbols/${encodeURIComponent(trimmedSymbol)}`);
    if (!response.ok) {
      throw new Error('not-found');
    }
    const payload = await response.json();
    renderPayloadIntoContainer(container, payload);
    if (title) {
      title.textContent = payload.title || trimmedSymbol;
    }
    if (subtitle) {
      subtitle.textContent = payload.subtitle || 'Walk-forward OOS mum verisi';
    }
    if (meta) {
      meta.textContent = `${payload.trade_count || 0} OOS islem · ${payload.return_pct ?? 0}% getiri · ${payload.walk_forward_window_count || 0} pencere · ${payload.data_source || 'Veri yok'}`;
    }
    if (status) {
      status.textContent = `${trimmedSymbol} walk-forward OOS backtesti yuklendi.`;
    }
    setLoadingProgress(100, `${trimmedSymbol} walk-forward OOS grafigi hazir.`);
  } catch (error) {
    destroyChart(container);
    container.innerHTML = '<div class="chart-empty">Bu hisse icin walk-forward OOS grafigi bulunamadi.</div>';
    if (status) {
      status.textContent = `${trimmedSymbol} icin walk-forward OOS kaydi bulunamadi.`;
    }
    setLoadingProgress(100, `${trimmedSymbol} icin walk-forward OOS kaydi bulunamadi.`);
  } finally {
    window.setTimeout(() => {
      setLoadingVisible(false);
    }, 180);
  }
}

async function loadPaperTradeSymbolChart(symbol) {
  const browser = document.querySelector('[data-paper-trade-browser]');
  if (!browser) {
    return;
  }

  const trimmedSymbol = (symbol || '').trim().toUpperCase();
  const container = browser.querySelector('[data-paper-trade-chart-container]');
  const status = browser.querySelector('[data-paper-trade-symbol-status]');
  const title = browser.querySelector('[data-paper-trade-chart-title]');
  const subtitle = browser.querySelector('[data-paper-trade-chart-subtitle]');
  const meta = browser.querySelector('[data-paper-trade-chart-meta]');

  if (!trimmedSymbol) {
    if (status) {
      status.textContent = 'Lutfen once bir paper trade hissesi sec.';
    }
    return;
  }

  if (status) {
    status.textContent = `${trimmedSymbol} icin paper trade grafigi yukleniyor...`;
  }
  setLoadingVisible(true, `${trimmedSymbol} icin paper trade izleri aliniyor...`);
  setLoadingProgress(20, `${trimmedSymbol} icin paper trade izleri aliniyor...`);
  destroyChart(container);
  container.innerHTML = '<div class="chart-empty">Paper trade grafigi hazirlaniyor...</div>';

  try {
    await ensureChartLibrary();
    const response = await fetch(`/api/paper-trades/symbols/${encodeURIComponent(trimmedSymbol)}`);
    if (!response.ok) {
      throw new Error('not-found');
    }
    const payload = await response.json();
    renderPayloadIntoContainer(container, payload);
    if (title) {
      title.textContent = payload.title || trimmedSymbol;
    }
    if (subtitle) {
      subtitle.textContent = payload.subtitle || 'Paper trade giris/cikis izleri';
    }
    if (meta) {
      meta.textContent = `${payload.paper_trade_count || 0} islem · ${payload.closed_trade_count || 0} kapanan · ${payload.realized_return_pct ?? 0}% gerceklesen getiri · ${payload.data_source || 'Veri yok'}`;
    }
    if (status) {
      status.textContent = `${trimmedSymbol} paper trade grafigi yuklendi.`;
    }
    setLoadingProgress(100, `${trimmedSymbol} paper trade grafigi hazir.`);
  } catch (error) {
    destroyChart(container);
    container.innerHTML = '<div class="chart-empty">Bu sembol icin paper trade grafigi bulunamadi.</div>';
    if (status) {
      status.textContent = `${trimmedSymbol} icin paper trade kaydi bulunamadi.`;
    }
    setLoadingProgress(100, `${trimmedSymbol} icin paper trade kaydi bulunamadi.`);
  } finally {
    window.setTimeout(() => {
      setLoadingVisible(false);
    }, 180);
  }
}

function setupMarketBrowser() {
  const browser = document.querySelector('[data-market-browser]');
  if (!browser) {
    return Promise.resolve();
  }

  const input = browser.querySelector('[data-market-symbol-input]');
  const button = browser.querySelector('[data-market-symbol-load]');
  if (!input || !button) {
    return Promise.resolve();
  }

  button.addEventListener('click', () => {
    loadMarketSymbolChart(input.value);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      loadMarketSymbolChart(input.value);
    }
  });

  if (input.value) {
    return loadMarketSymbolChart(input.value);
  }
  return Promise.resolve();
}

function setupBacktestBrowser() {
  const browser = document.querySelector('[data-backtest-browser]');
  if (!browser) {
    return Promise.resolve();
  }

  const input = browser.querySelector('[data-backtest-symbol-input]');
  const button = browser.querySelector('[data-backtest-symbol-load]');
  if (!input || !button) {
    return Promise.resolve();
  }

  button.addEventListener('click', () => {
    loadBacktestSymbolChart(input.value);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      loadBacktestSymbolChart(input.value);
    }
  });

  if (input.value) {
    return loadBacktestSymbolChart(input.value);
  }
  return Promise.resolve();
}

function setupPaperTradeBrowser() {
  const browser = document.querySelector('[data-paper-trade-browser]');
  if (!browser) {
    return Promise.resolve();
  }

  const input = browser.querySelector('[data-paper-trade-symbol-input]');
  const button = browser.querySelector('[data-paper-trade-symbol-load]');
  if (!input || !button) {
    return Promise.resolve();
  }

  button.addEventListener('click', () => {
    loadPaperTradeSymbolChart(input.value);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      loadPaperTradeSymbolChart(input.value);
    }
  });

  if (input.value) {
    return loadPaperTradeSymbolChart(input.value);
  }
  return Promise.resolve();
}

function setupRefreshButton() {
  const button = document.querySelector('[data-refresh-cache]');
  if (!button) {
    return;
  }
  button.addEventListener('click', async () => {
    button.disabled = true;
    setLoadingVisible(true, 'Yalnizca eksik veri guncelleniyor ve arastirma snapshot yenileniyor...');
    setLoadingProgress(0, 'Yalnizca eksik veri guncelleniyor ve arastirma snapshot yenileniyor...');
    try {
      const response = await fetch('/api/cache/refresh', { method: 'POST' });
      if (!response.ok) {
        throw new Error('refresh-failed');
      }
      const payload = await response.json();
      const jobId = payload.job_id;
      if (!jobId) {
        throw new Error('refresh-job-missing');
      }
      await pollRefreshJob(jobId);
      window.location.reload();
    } catch (error) {
      setLoadingVisible(false);
      button.disabled = false;
      window.alert('Veri guncelleme basarisiz oldu.');
    }
  });
}

async function pollRefreshJob(jobId) {
  while (true) {
    const response = await fetch(`/api/cache/refresh/${encodeURIComponent(jobId)}`);
    if (!response.ok) {
      throw new Error('refresh-status-failed');
    }
    const payload = await response.json();
    const progress = Number(payload.progress || 0);
    const message = payload.message || 'Veri guncelleniyor...';
    setLoadingProgress(progress, `${message} (%${progress})`);

    if (payload.status === 'completed') {
      setLoadingProgress(100, 'Veri guncelleme tamamlandi. Sayfa yenileniyor...');
      return payload;
    }
    if (payload.status === 'failed') {
      throw new Error(payload.error || 'refresh-failed');
    }
    await new Promise((resolve) => window.setTimeout(resolve, 800));
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  setLoadingVisible(true, 'Onbellek ve grafikler hazirlaniyor...');
  setLoadingProgress(12, 'Onbellek ve grafikler hazirlaniyor...');
  await ensureChartLibrary();
  setLoadingProgress(32, 'Grafik kutuphanesi hazirlaniyor...');
  renderStaticCharts();
  setupRefreshButton();
  await setupMarketBrowser();
  await setupPaperTradeBrowser();
  await setupBacktestBrowser();
  setLoadingProgress(100, 'Sayfa hazir.');
  setLoadingVisible(false);
});
