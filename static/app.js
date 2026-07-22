const state = {
  functions: [],
  dates: [],
  selectedDate: localStorage.getItem('stock-control-date') || '',
  selectedKey: localStorage.getItem('stock-control-selected') || 'limit_up_red_arrow',
  selectedFunction: null,
  currentRun: null,
  currentKlineCode: '',
  fearGreed: null,
  backtestResult: null,
  serenityResult: null,
  serenityProgressTimer: null,
  marketState: { market_open: false, now: '', timezone: 'Asia/Taipei' },
  selfUpdateProgressTimer: null,
  updateStatusChecked: false,
};

const KLINE_MODAL_CACHE_MAX_ENTRIES = 120;
const klineModalCache = new Map();

const elements = {
  groups: document.getElementById('function-groups'),
  title: document.getElementById('function-title'),
  description: document.getElementById('function-description'),
  runButton: document.getElementById('run-button'),
  statusPill: document.getElementById('status-pill'),
  latestMeta: document.getElementById('latest-meta'),
  latestOutput: document.getElementById('latest-output'),
  artifactList: document.getElementById('artifact-list'),
  refreshButton: document.getElementById('refresh-button'),
  serenityButton: document.getElementById('serenity-button'),
  serenityPanel: document.getElementById('serenity-panel'),
  serenityStatusPill: document.getElementById('serenity-status-pill'),
  serenityMeta: document.getElementById('serenity-meta'),
  serenityOutput: document.getElementById('serenity-output'),
  institutionalButton: document.getElementById('institutional-button'),
  intradayButton: document.getElementById('intraday-button'),
  refreshFutureButton: document.getElementById('refresh-future-button'),
  dateControlWrap: document.getElementById('date-control-wrap'),
  dateInput: document.getElementById('date-input'),
  dateNote: document.getElementById('date-note'),
  settingsButton: document.getElementById('settings-button'),
  selfUpdateButton: document.getElementById('self-update-button'),
  selfUpdateProgress: document.getElementById('self-update-progress'),
  selfUpdateProgressText: document.getElementById('self-update-progress-text'),
  settingsModal: document.getElementById('settings-modal'),
  settingsClose: document.getElementById('settings-close'),
  settingsForm: document.getElementById('settings-form'),
  finmindTokenInput: document.getElementById('finmind-token-input'),
  fugleTokenInput: document.getElementById('fugle-token-input'),
  finmindTokenHint: document.getElementById('finmind-token-hint'),
  fugleTokenHint: document.getElementById('fugle-token-hint'),
  settingsMeta: document.getElementById('settings-meta'),
  settingsSave: document.getElementById('settings-save'),
  klineModal: document.getElementById('kline-modal'),
  klineModalBody: document.getElementById('kline-modal-body'),
  klineModalTitle: document.getElementById('kline-modal-title'),
  klineModalMeta: document.getElementById('kline-modal-meta'),
  klineModalClose: document.getElementById('kline-modal-close'),
  backtestPanel: document.getElementById('backtest-panel'),
  backtestStartDate: document.getElementById('backtest-start-date'),
  backtestEndDate: document.getElementById('backtest-end-date'),
  backtestTp: document.getElementById('backtest-tp'),
  backtestSl: document.getElementById('backtest-sl'),
  backtestEntryMax: document.getElementById('backtest-entry-max'),
  backtestEntryMin: document.getElementById('backtest-entry-min'),
  backtestTopN: document.getElementById('backtest-top-n'),
  backtestRunButton: document.getElementById('backtest-run-button'),
  backtestStatusPill: document.getElementById('backtest-status-pill'),
  backtestMeta: document.getElementById('backtest-meta'),
  backtestOutput: document.getElementById('backtest-output'),
};

function setStatus(text, tone = 'neutral') {
  elements.statusPill.textContent = text;
  elements.statusPill.className = `status-pill ${tone}`;
}

function startSelfUpdateProgress() {
  const steps = ['準備檢查版本...', '正在連線 GitHub...', '正在下載更新...', '正在套用更新...'];
  let index = 0;
  elements.selfUpdateProgress.classList.remove('hidden');
  elements.selfUpdateProgress.setAttribute('aria-hidden', 'false');
  elements.selfUpdateProgressText.textContent = steps[0];
  if (state.selfUpdateProgressTimer) {
    clearInterval(state.selfUpdateProgressTimer);
  }
  state.selfUpdateProgressTimer = window.setInterval(() => {
    index = (index + 1) % steps.length;
    elements.selfUpdateProgressText.textContent = steps[index];
  }, 1400);
}

function stopSelfUpdateProgress(finalText = '') {
  if (state.selfUpdateProgressTimer) {
    clearInterval(state.selfUpdateProgressTimer);
    state.selfUpdateProgressTimer = null;
  }
  if (finalText) {
    elements.selfUpdateProgressText.textContent = finalText;
    window.setTimeout(() => {
      elements.selfUpdateProgress.classList.add('hidden');
      elements.selfUpdateProgress.setAttribute('aria-hidden', 'true');
    }, 900);
    return;
  }
  elements.selfUpdateProgress.classList.add('hidden');
  elements.selfUpdateProgress.setAttribute('aria-hidden', 'true');
}

function applyUpdateButtonState(payload, fallbackText = '一鍵更新') {
  const buttonLabel = payload?.button_label || fallbackText;
  const buttonEnabled = Boolean(payload?.button_enabled);
  elements.selfUpdateButton.textContent = buttonLabel;
  elements.selfUpdateButton.disabled = !buttonEnabled;
  elements.selfUpdateButton.title = buttonEnabled ? '從 GitHub 更新目前程式' : '目前已是最新版本';
  state.updateStatusChecked = true;
}

async function checkUpdateStatus() {
  elements.selfUpdateButton.textContent = '檢查更新中';
  elements.selfUpdateButton.disabled = true;
  elements.selfUpdateButton.title = '背景檢查是否有新版本';
  try {
    const response = await fetch('/api/update_status');
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || '檢查更新失敗');
    }
    applyUpdateButtonState(payload);
  } catch (error) {
    elements.selfUpdateButton.textContent = '一鍵更新';
    elements.selfUpdateButton.disabled = false;
    elements.selfUpdateButton.title = String(error.message || error);
  }
}

function statusTone(status) {
  if (status === 'success') return 'success';
  if (status === 'failed') return 'failed';
  if (status === 'running') return 'running';
  return 'neutral';
}

function formatDuration(value) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(3)} 秒`;
}

function compactTimestamp(value) {
  if (!value) return '—';
  return value.replace('T', ' ').replace(/\+.*$/, '');
}

function formatYmd(value) {
  if (!value || value.length !== 8) return value || '—';
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

function toInputDate(value) {
  return formatYmd(value);
}

function fromInputDate(value) {
  if (!value) return '';
  return value.replaceAll('-', '');
}

function isPreBreakoutFunction(functionKey = state.selectedKey) {
  return functionKey === 'pre_breakout_standard' || functionKey === 'pre_breakout_conservative';
}

function isBacktestFunction(functionKey = state.selectedKey) {
  return isPreBreakoutFunction(functionKey);
}

function isFearGreedFunction(functionKey = state.selectedKey) {
  return functionKey === 'cnn_fear_greed_index';
}

function isIntradayFunction(functionKey = state.selectedKey) {
  return [
    'pre_breakout_conservative',
    'pre_breakout_standard',
    'ma_bullish_turning_point',
    'limit_up_red_arrow',
  ].includes(functionKey);
}

function isIntradayAvailable() {
  return isIntradayFunction() && Boolean(state.selectedDate) && Boolean(state.marketState?.market_open);
}

function getInstitutionalMap() {
  return state.currentRun?.institutional?.payload?.stocks || {};
}

function getIntradayMap() {
  return state.currentRun?.intraday?.payload?.quotes || {};
}

function getCurrentSerenityStocks() {
  if (!state.currentRun || state.currentRun.status !== 'success') return [];
  const text = state.currentRun.output_text || '';
  let parsed = parsePreBreakoutOutput(text);
  let stocks = parsed?.stocks || [];

  if (!stocks.length) {
    parsed = parseLimitUpOutput(text);
    stocks = parsed ? enrichMaBullishStocks(parsed.stocks, parsed.sector) : [];
  }
  if (!stocks.length) {
    parsed = parseMaBullishOutput(text);
    stocks = parsed ? enrichMaBullishStocks(parsed.stocks, parsed.sector) : [];
  }

  return stocks.slice(0, 30).map((stock) => ({
    code: stock.code || '',
    name: stock.name || '',
    theme: stock.themeName || '',
    grade: stock.grade || '',
    rank_score: stock.rankScore || '',
    close: stock.close || '',
    volume: stock.volume || '',
  })).filter((stock) => stock.code);
}

function setSerenityStatus(text, tone = 'neutral') {
  elements.serenityStatusPill.textContent = text;
  elements.serenityStatusPill.className = `status-pill ${tone}`;
}

function resetSerenityPanel(message = '按上方「Serenity 深度分析」，會把目前候選股送給 Hermes 進行供應鏈瓶頸研究。') {
  if (state.serenityProgressTimer) {
    clearInterval(state.serenityProgressTimer);
    state.serenityProgressTimer = null;
  }
  state.serenityResult = null;
  elements.serenityMeta.innerHTML = '';
  elements.serenityOutput.className = 'serenity-output empty-block';
  elements.serenityOutput.textContent = message;
  setSerenityStatus('待命', 'neutral');
}

function renderActionButtons() {
  const isFearGreed = isFearGreedFunction();
  const showSerenity = !isFearGreed && Boolean(state.selectedFunction?.executable);
  const serenityStocks = getCurrentSerenityStocks();
  const showInstitutional = !isFearGreed && isPreBreakoutFunction() && Boolean(state.selectedDate);
  const showIntraday = !isFearGreed && isIntradayFunction() && Boolean(state.selectedDate);
  const showBacktest = !isFearGreed && isBacktestFunction();
  elements.dateControlWrap.hidden = isFearGreed;
  elements.runButton.hidden = !state.selectedFunction?.executable;
  elements.refreshFutureButton.hidden = isFearGreed || !state.selectedFunction?.executable;
  elements.serenityButton.hidden = !showSerenity;
  elements.serenityPanel.hidden = !showSerenity;
  elements.serenityButton.disabled = !serenityStocks.length;
  elements.serenityButton.title = serenityStocks.length
    ? `分析目前 ${serenityStocks.length} 檔候選股`
    : '請先執行選股，產生候選股票後才能分析';
  elements.institutionalButton.hidden = !showInstitutional;
  elements.intradayButton.hidden = !showIntraday;
  elements.intradayButton.disabled = !isIntradayAvailable();
  elements.intradayButton.title = isIntradayAvailable() ? '' : '僅盤中時段可用';
  elements.backtestPanel.hidden = !showBacktest;
}

async function fetchSettingsPayload() {
  const response = await fetch('/api/settings');
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || '讀取設定失敗');
  }
  return payload;
}

async function loadSettingsIntoForm() {
  const payload = await fetchSettingsPayload();
  elements.finmindTokenInput.value = payload.finmind_token || '';
  elements.fugleTokenInput.value = payload.fugle_intraday_api_key || '';
  elements.finmindTokenHint.textContent = payload.has_finmind_token ? `已設定：${payload.masked_finmind_token}` : '未設定';
  elements.fugleTokenHint.textContent = payload.has_fugle_intraday_api_key ? `已設定：${payload.masked_fugle_intraday_api_key}` : '未設定';
  elements.settingsMeta.textContent = '設定會寫入 \\StockControlPanel\\.env';
}

async function ensureTokenConfigured(kind) {
  const settings = await fetchSettingsPayload();
  if (kind === 'fugle' && settings.has_fugle_intraday_api_key) return true;
  if (kind === 'finmind' && settings.has_finmind_token) return true;

  const missingLabel = kind === 'fugle' ? 'FUGLE_INTRADAY_API_KEY' : 'FINMIND_TOKEN';
  const actionLabel = kind === 'fugle' ? '即時行情' : '法人查詢';
  setStatus(`${actionLabel}缺少 Token`, 'failed');
  renderPlainOutput(`主人，${actionLabel}前要先到設定頁填入 ${missingLabel}。`, 'error-output');
  openSettingsModal();
  return false;
}

function openSettingsModal() {
  elements.settingsModal.classList.remove('hidden');
  elements.settingsModal.setAttribute('aria-hidden', 'false');
  loadSettingsIntoForm().catch((error) => {
    setStatus(String(error.message || error), 'failed');
  });
}

function closeSettingsModal() {
  elements.settingsModal.classList.add('hidden');
  elements.settingsModal.setAttribute('aria-hidden', 'true');
}

async function saveSettings(event) {
  event.preventDefault();
  elements.settingsSave.disabled = true;
  setStatus('儲存設定中...', 'running');

  try {
    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        finmind_token: elements.finmindTokenInput.value.trim(),
        fugle_intraday_api_key: elements.fugleTokenInput.value.trim(),
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || '儲存設定失敗');
    }
    await loadSettingsIntoForm();
    setStatus('設定已儲存', 'success');
    closeSettingsModal();
  } catch (error) {
    setStatus(String(error.message || error), 'failed');
  } finally {
    elements.settingsSave.disabled = false;
  }
}

async function runSelfUpdate() {
  if (elements.selfUpdateButton.disabled && state.updateStatusChecked) return;
  const confirmed = window.confirm('即將從 GitHub 更新這個程式。更新完成後需要手動重新啟動，是否繼續？');
  if (!confirmed) return;

  elements.selfUpdateButton.disabled = true;
  elements.selfUpdateButton.textContent = '更新中';
  setStatus('更新中...', 'running');
  startSelfUpdateProgress();

  try {
    const response = await fetch('/api/self_update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || '自動更新失敗');
    }

    setStatus(payload.updated ? '更新完成，請重啟' : '目前已是最新版本', 'success');
    stopSelfUpdateProgress(payload.updated ? '更新完成' : '已是最新版本');
    applyUpdateButtonState({
      button_label: payload.updated ? '請重新啟動' : '已是最新版',
      button_enabled: false,
    }, payload.updated ? '請重新啟動' : '已是最新版');
    if (payload.updated) {
      window.alert('更新完成，請直接重新啟動程式即可；啟動器會自動關閉舊的 8765 服務，且不會再留下黑色終端機視窗，不需要再手動執行 stop_8765_port.bat。');
    } else {
      window.alert('目前已是最新版本。');
    }
  } catch (error) {
    setStatus(String(error.message || error), 'failed');
    stopSelfUpdateProgress('更新失敗');
    elements.selfUpdateButton.textContent = '一鍵更新';
    elements.selfUpdateButton.disabled = false;
    elements.selfUpdateButton.title = '從 GitHub 更新目前程式';
    window.alert(String(error.message || error));
  }
}

function floorVolumeText(value) {
  const match = String(value || '').match(/([\d.]+)/);
  if (!match) return String(value || '');
  return String(Math.floor(Number(match[1])));
}

function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatPrice(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return number.toFixed(2);
}

function formatVolume(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return `${Math.round(number).toLocaleString('zh-TW')} 張`;
}

function formatIntradayTime(microseconds) {
  const number = Number(microseconds);
  if (!Number.isFinite(number) || number <= 0) return '—';
  const date = new Date(number / 1000);
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

function formatChangePercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const sign = number > 0 ? '+' : '';
  return `${sign}${number.toFixed(2)}%`;
}

function toneClassFromNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  if (number > 0) return 'up-text';
  if (number < 0) return 'down-text';
  return '';
}

function buildCodeButton(stock) {
  return `<button class="stock-code-button" data-stock-code="${escapeHtml(stock.code)}" data-stock-name="${escapeHtml(stock.name)}">${escapeHtml(stock.code)}</button>`;
}

function buildInlineKlineSlot(stock) {
  return `<td class="td-mini-kline"><div class="mini-kline-slot" data-inline-kline="${escapeHtml(stock.code)}">載入中...</div></td>`;
}

function renderMiniKlineSvg(rows) {
  if (!rows || !rows.length) {
    return '<div class="mini-kline-empty">—</div>';
  }

  const width = 168;
  const height = 48;
  const padX = 4;
  const padY = 5;
  const highs = rows.map((item) => Number(item.high));
  const lows = rows.map((item) => Number(item.low));
  const maxHigh = Math.max(...highs);
  const minLow = Math.min(...lows);
  const priceSpan = Math.max(maxHigh - minLow, 0.01);
  const plotWidth = width - padX * 2;
  const candleGap = plotWidth / Math.max(rows.length, 1);
  const candleWidth = Math.max(1.2, Math.min(3.6, candleGap * 0.64));
  const priceToY = (value) => padY + ((maxHigh - Number(value)) / priceSpan) * (height - padY * 2);

  let markup = '';
  rows.forEach((row, index) => {
    const x = padX + candleGap * index + candleGap / 2;
    const open = Number(row.open);
    const close = Number(row.close);
    const high = Number(row.high);
    const low = Number(row.low);
    const rising = close >= open;
    const color = rising ? '#c83f49' : '#1e8e5a';
    const bodyTop = priceToY(Math.max(open, close));
    const bodyBottom = priceToY(Math.min(open, close));
    const bodyHeight = Math.max(bodyBottom - bodyTop, 1.2);

    markup += `<line x1="${x.toFixed(2)}" y1="${priceToY(high).toFixed(2)}" x2="${x.toFixed(2)}" y2="${priceToY(low).toFixed(2)}" stroke="${color}" stroke-width="0.9"></line>`;
    markup += `<rect x="${(x - candleWidth / 2).toFixed(2)}" y="${bodyTop.toFixed(2)}" width="${candleWidth.toFixed(2)}" height="${bodyHeight.toFixed(2)}" fill="${rising ? color : '#ffffff'}" stroke="${color}" stroke-width="0.9" rx="0.5"></rect>`;
  });

  return `<svg class="mini-kline-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">${markup}</svg>`;
}

async function hydrateInlineKlines(stocks) {
  const codes = [...new Set((stocks || []).map((stock) => String(stock.code || '').trim()).filter(Boolean))];
  if (!codes.length || !state.selectedDate) return;

  try {
    const response = await fetch('/api/kline_batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        codes,
        end_date: state.selectedDate,
        lookback_days: 40,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || '載入 40 天 K 線縮圖失敗');
    }

    for (const code of codes) {
      const holder = elements.latestOutput.querySelector(`[data-inline-kline="${CSS.escape(code)}"]`);
      if (!holder) continue;
      const item = payload.items?.[code];
      if (!item || item.error) {
        holder.innerHTML = '<div class="mini-kline-empty">—</div>';
        continue;
      }
      holder.innerHTML = renderMiniKlineSvg(item.rows || []);
      holder.title = `${code}｜${item.name || ''}｜${formatYmd(item.start_date)} ～ ${formatYmd(item.end_date)}｜40日K線`;
    }
  } catch (error) {
    for (const code of codes) {
      const holder = elements.latestOutput.querySelector(`[data-inline-kline="${CSS.escape(code)}"]`);
      if (holder) {
        holder.innerHTML = '<div class="mini-kline-empty">—</div>';
      }
    }
  }
}

function closeKlineModal() {
  elements.klineModal.classList.add('hidden');
  elements.klineModal.setAttribute('aria-hidden', 'true');
  state.currentKlineCode = '';
}

function klineModalCacheKey(code, endDate, lookbackDays = 60) {
  return `${String(code || '').trim()}::${String(endDate || '').trim()}::${Number(lookbackDays) || 60}`;
}

function getCachedKlineModalPayload(code, endDate, lookbackDays = 60) {
  const key = klineModalCacheKey(code, endDate, lookbackDays);
  if (!klineModalCache.has(key)) return null;
  const payload = klineModalCache.get(key);
  klineModalCache.delete(key);
  klineModalCache.set(key, payload);
  return payload;
}

function setCachedKlineModalPayload(payload, endDate, lookbackDays = 60) {
  if (!payload?.code || !endDate) return;
  const key = klineModalCacheKey(payload.code, endDate, lookbackDays);
  if (klineModalCache.has(key)) {
    klineModalCache.delete(key);
  }
  klineModalCache.set(key, payload);
  while (klineModalCache.size > KLINE_MODAL_CACHE_MAX_ENTRIES) {
    const oldestKey = klineModalCache.keys().next().value;
    if (!oldestKey) break;
    klineModalCache.delete(oldestKey);
  }
}

function openKlineModalShell(code, name) {
  state.currentKlineCode = code;
  elements.klineModal.classList.remove('hidden');
  elements.klineModal.setAttribute('aria-hidden', 'false');
  elements.klineModalTitle.textContent = `${code} ${name}｜60 日 K 線圖`;
  elements.klineModalMeta.textContent = `截至 ${formatYmd(state.selectedDate)} ｜ 載入中...`;
  elements.klineModalBody.innerHTML = '<div class="kline-loading">K 線資料載入中...</div>';
}

function linePath(points) {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ');
}

function renderKlineModal(payload) {
  const rows = payload.rows || [];
  if (!rows.length) {
    elements.klineModalBody.innerHTML = '<div class="empty-block">目前沒有可顯示的 K 線資料。</div>';
    return;
  }

  const closes = rows.map((item) => Number(item.close));
  const highs = rows.map((item) => Number(item.high));
  const lows = rows.map((item) => Number(item.low));
  const volumes = rows.map((item) => Number(item.volume));
  const maxHigh = Math.max(...highs);
  const minLow = Math.min(...lows);
  const maxVolume = Math.max(...volumes, 1);
  const priceSpan = Math.max(maxHigh - minLow, 0.01);

  const chartWidth = 1040;
  const priceHeight = 360;
  const volumeHeight = 110;
  const volumeTop = priceHeight + 34;
  const chartHeight = volumeTop + volumeHeight + 36;
  const padLeft = 64;
  const padRight = 26;
  const plotWidth = chartWidth - padLeft - padRight;
  const candleGap = plotWidth / Math.max(rows.length, 1);
  const candleWidth = Math.max(4, Math.min(10, candleGap * 0.56));

  const priceToY = (value) => 20 + ((maxHigh - Number(value)) / priceSpan) * (priceHeight - 40);
  const volumeToY = (value) => volumeTop + volumeHeight - (Number(value) / maxVolume) * (volumeHeight - 12);
  const xAt = (index) => padLeft + candleGap * index + candleGap / 2;

  let priceGrid = '';
  for (let i = 0; i <= 4; i += 1) {
    const y = 20 + ((priceHeight - 40) / 4) * i;
    const price = (maxHigh - (priceSpan / 4) * i).toFixed(2);
    priceGrid += `<line x1="${padLeft}" y1="${y}" x2="${chartWidth - padRight}" y2="${y}" class="kline-grid-line"></line>`;
    priceGrid += `<text x="${padLeft - 10}" y="${y + 4}" class="kline-axis-text" text-anchor="end">${price}</text>`;
  }

  const maSeries = [
    { values: payload.ma5 || [], color: '#1f77b4' },
    { values: payload.ma10 || [], color: '#ff7f0e' },
    { values: payload.ma20 || [], color: '#222222' },
  ];

  let maPaths = '';
  for (const series of maSeries) {
    const points = series.values
      .map((value, index) => (value === null || value === undefined ? null : [xAt(index), priceToY(value)]))
      .filter(Boolean);
    if (!points.length) continue;
    maPaths += `<path d="${linePath(points)}" fill="none" stroke="${series.color}" stroke-width="1.8"></path>`;
  }

  let candles = '';
  let xLabels = '';
  rows.forEach((row, index) => {
    const x = xAt(index);
    const open = Number(row.open);
    const close = Number(row.close);
    const high = Number(row.high);
    const low = Number(row.low);
    const rising = close >= open;
    const color = rising ? '#c83f49' : '#1e8e5a';
    const bodyTop = priceToY(Math.max(open, close));
    const bodyBottom = priceToY(Math.min(open, close));
    const bodyHeight = Math.max(bodyBottom - bodyTop, 1.6);
    const volumeY = volumeToY(row.volume);
    const label = `${row.date.slice(4, 6)}/${row.date.slice(6, 8)}`;

    candles += `<line x1="${x}" y1="${priceToY(high)}" x2="${x}" y2="${priceToY(low)}" stroke="${color}" stroke-width="1.2"></line>`;
    candles += `<rect x="${x - candleWidth / 2}" y="${bodyTop}" width="${candleWidth}" height="${bodyHeight}" fill="${rising ? color : '#ffffff'}" stroke="${color}" stroke-width="1.2" rx="1"></rect>`;
    candles += `<rect x="${x - candleWidth / 2}" y="${volumeY}" width="${candleWidth}" height="${Math.max(volumeTop + volumeHeight - volumeY, 1)}" fill="${color}" opacity="0.8"></rect>`;

    if (index === 0 || index === rows.length - 1 || index % 10 === 0) {
      xLabels += `<text x="${x}" y="${chartHeight - 10}" class="kline-axis-text" text-anchor="middle">${label}</text>`;
    }
  });

  const latest = rows[rows.length - 1];
  const latestMa5 = payload.ma5?.[payload.ma5.length - 1];
  const latestMa10 = payload.ma10?.[payload.ma10.length - 1];
  const latestMa20 = payload.ma20?.[payload.ma20.length - 1];

  elements.klineModalTitle.textContent = `${payload.code} ${payload.name}｜60 日 K 線圖`;
  elements.klineModalMeta.textContent = `${payload.market} ｜ ${formatYmd(payload.start_date)} ～ ${formatYmd(payload.end_date)} ｜ 共 ${payload.count} 根`;
  elements.klineModalBody.innerHTML = `
    <div class="kline-summary-grid">
      <div class="summary-chip"><span>最新收盤</span><strong>${formatPrice(latest.close)}</strong></div>
      <div class="summary-chip"><span>最新開高低</span><strong>${formatPrice(latest.open)} / ${formatPrice(latest.high)} / ${formatPrice(latest.low)}</strong></div>
      <div class="summary-chip"><span>最新成交量</span><strong>${formatVolume(latest.volume)}</strong></div>
      <div class="summary-chip"><span>均線</span><strong>MA5 ${latestMa5 ? formatPrice(latestMa5) : '—'} ｜ MA10 ${latestMa10 ? formatPrice(latestMa10) : '—'} ｜ MA20 ${latestMa20 ? formatPrice(latestMa20) : '—'}</strong></div>
    </div>
    <div class="kline-chart-wrap">
      <svg class="kline-svg" viewBox="0 0 ${chartWidth} ${chartHeight}" preserveAspectRatio="xMidYMid meet">
        ${priceGrid}
        <line x1="${padLeft}" y1="${volumeTop}" x2="${chartWidth - padRight}" y2="${volumeTop}" class="kline-grid-line bold"></line>
        ${maPaths}
        ${candles}
        ${xLabels}
      </svg>
      <div class="kline-legend">
        <span><i class="legend-swatch red"></i>上漲 K 棒</span>
        <span><i class="legend-swatch green"></i>下跌 K 棒</span>
        <span><i class="legend-swatch blue"></i>MA5</span>
        <span><i class="legend-swatch orange"></i>MA10</span>
        <span><i class="legend-swatch black"></i>MA20</span>
      </div>
    </div>`;
}

async function openKlineModal(code, name) {
  if (!code) return;
  const lookbackDays = 60;
  openKlineModalShell(code, name || '');

  const cachedPayload = getCachedKlineModalPayload(code, state.selectedDate, lookbackDays);
  if (cachedPayload) {
    if (state.currentKlineCode !== code) return;
    renderKlineModal(cachedPayload);
    return;
  }

  try {
    const query = new URLSearchParams({
      end_date: state.selectedDate,
      lookback_days: String(lookbackDays),
    });
    const response = await fetch(`/api/kline/${encodeURIComponent(code)}?${query.toString()}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || '讀取 K 線資料失敗');
    }
    setCachedKlineModalPayload(payload, state.selectedDate, lookbackDays);
    if (state.currentKlineCode !== code) return;
    renderKlineModal(payload);
  } catch (error) {
    elements.klineModalBody.innerHTML = `<div class="empty-block">${escapeHtml(String(error.message || error))}</div>`;
    elements.klineModalMeta.textContent = `截至 ${formatYmd(state.selectedDate)} ｜ 讀取失敗`;
  }
}

function renderGroups() {
  const grouped = new Map();
  for (const item of state.functions) {
    if (!grouped.has(item.category)) grouped.set(item.category, []);
    grouped.get(item.category).push(item);
  }

  elements.groups.innerHTML = '';
  for (const [category, items] of grouped.entries()) {
    const block = document.createElement('section');
    block.className = 'group-block';

    const title = document.createElement('h3');
    title.className = 'group-title';
    title.textContent = category;
    block.appendChild(title);

    for (const item of items) {
      const button = document.createElement('button');
      button.className = 'function-button';
      if (item.key === state.selectedKey) button.classList.add('active');
      button.innerHTML = `<span class="name">${item.name}</span>`;
      button.addEventListener('click', () => selectFunction(item.key));
      block.appendChild(button);
    }

    elements.groups.appendChild(block);
  }
}

function renderDateOptions() {
  const hasDates = Boolean(state.dates.length);
  const earliest = hasDates ? state.dates[state.dates.length - 1] : '';
  const latest = hasDates ? state.dates[0] : '';

  elements.dateInput.value = state.selectedDate ? toInputDate(state.selectedDate) : '';
  elements.dateInput.min = earliest ? toInputDate(earliest) : '';
  elements.dateInput.max = latest ? toInputDate(latest) : '';
  elements.dateInput.disabled = !hasDates;

  if (hasDates) {
    elements.dateNote.textContent = `可選擇的日期：${toInputDate(earliest).replaceAll('-', '/')} 起的交易日`;
  } else {
    elements.dateNote.textContent = '目前沒有可選日期';
  }
}


function parseLimitUpOutput(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.includes('策略：前一交易日漲停') || line.includes('策略：指定日期漲停'))) return null;

  const summary = {};
  const stocks = [];
  for (const line of lines) {
    if (line.startsWith('比較區間：')) summary.range = line.replace('比較區間：', '').trim();
    if (line.startsWith('參考前日：')) summary.referenceDate = line.replace('參考前日：', '').trim();
    if (line.startsWith('入選數量：')) summary.count = line.replace('入選數量：', '').trim();
    const match = line.match(/^(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+.+?C=([\d.]+)\s+V=([\d.]+張)(?:\s+\|\s+上影=([\d.]+)\s+實體=([\d.]+)\s+比=([\d.-]+))?(?:\s+分數=([\d.]+))?(?:\s+\|\s+後5日=(.+))?$/);
    if (match) {
      const futureText = (match[10] || '').trim();
      const futureDays = futureText === '(無後續資料)'
        ? []
        : futureText.split(/,\s*/).map((entry) => {
            // 新格式: 20260617:181.50/-5.96%/-5.96%  (兩個百分比)
            let fm = entry.match(/^(\d{8}):([\d.]+)\/([+-]\d+\.\d+%)\/([+-]\d+\.\d+%)$/);
            if (fm) {
              return {
                date: fm[1],
                close: fm[2],
                pctFromSignal: fm[3],
                pctFromPrev: fm[4],
              };
            }
            // 舊格式: 20260616:59.70/-5.09%  (只有一個百分比=對訊號日)
            fm = entry.match(/^(\d{8}):([\d.]+)\/([+-]\d+\.\d+%)$/);
            if (fm) {
              return {
                date: fm[1],
                close: fm[2],
                pctFromSignal: fm[3],
                pctFromPrev: fm[3], // 舊格式只有一個，當作對訊號日+市場口徑都顯示同值
              };
            }
            return null;
          }).filter(Boolean);
      stocks.push({
        market: match[1],
        code: match[2],
        name: match[3],
        close: match[4],
        volume: floorVolumeText(match[5]),
        rankScore: match[9] || '',
        futureDays,
      });
    }
  }
  return { type: 'limit_up', summary, stocks, sector: parseSectorQuickOutput(text) };
}

function parsePreBreakoutOutput(text) {
  const lines = text.split('\n').map((line) => line.trimEnd());
  if (!lines.some((line) => line.includes('PRE-BREAKOUT'))) return null;

  const summary = {};
  const stocks = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('🔍 交易日：') || trimmed.startsWith('交易日：')) {
      summary.date = trimmed.replace(/^🔍\s*/, '').replace('交易日：', '').trim();
    }
    if (trimmed.startsWith('📈 漲停家數：') || trimmed.startsWith('漲停家數：')) {
      summary.heat = trimmed.replace(/^📈\s*/, '').trim();
    }
    if (trimmed.startsWith('通過篩選：')) summary.count = trimmed.replace('通過篩選：', '').trim();
    const match = trimmed.match(/^([ABC])\s+(\d+)\s+(\S+)\s+\|\s+C=([\d.]+)\s+V=(\d+)張(?:\s+分數=([\d.]+))?\s+\|\s+後5日=(.+)$/);
    if (match) {
      const futureRaw = match[7].trim();
      const futureDays = futureRaw === '(無後續資料)'
        ? []
        : futureRaw.split(/\s*,\s*/).map((chunk) => {
            const parts = chunk.match(/^(\d{8}):([\d.]+)\/([+-]?[\d.]+%)\/([+-]?[\d.]+%)$/);
            if (!parts) return null;
            return {
              date: parts[1],
              close: parts[2],
              pctFromSignal: parts[3],
              pctFromPrev: parts[4],
            };
          }).filter(Boolean);
      stocks.push({
        grade: match[1],
        code: match[2],
        name: match[3],
        close: match[4],
        volume: match[5],
        rankScore: match[6] || '',
        futureDays,
      });
    }
  }
  return { type: 'pre_breakout', summary, stocks };
}

function parseMaBullishOutput(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.includes('策略：最近交易日剛達成 MA5 > MA10 > MA20'))) return null;

  const summary = {};
  const stocks = [];
  for (const line of lines) {
    if (line.startsWith('比較區間：')) summary.range = line.replace('比較區間：', '').trim();
    if (line.startsWith('入選數量：')) summary.count = line.replace('入選數量：', '').trim();

    const match = line.match(/^(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+C=([\d.]+)\s+V=([\d.]+)張\s+倍數=([\d.]+)(?:\s+分數=([\d.]+))?\s+\|\s+後5日=(.+)$/);
    if (match) {
      const futureRaw = match[8].trim();
      const futureDays = futureRaw === '(無後續資料)'
        ? []
        : futureRaw.split(/\s*,\s*/).map((chunk) => {
            const parts = chunk.match(/^(\d{8}):([\d.]+)\/([+-]?[\d.]+%)\/([+-]?[\d.]+%)$/);
            if (!parts) return null;
            return {
              date: parts[1],
              close: parts[2],
              pctFromSignal: parts[3],
              pctFromPrev: parts[4],
            };
          }).filter(Boolean);

      stocks.push({
        market: match[1],
        code: match[2],
        name: match[3],
        close: match[4],
        volume: floorVolumeText(match[5]),
        multiple: match[6],
        rankScore: match[7] || '',
        futureDays,
      });
    }
  }
  return { type: 'ma_bullish', summary, stocks, sector: parseSectorQuickOutput(text) };
}

function parseSectorQuickOutput(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.includes('策略：0121 快速族群分析') || line.includes('策略：今日漲停 快速族群分析'))) return null;

  const result = {
    firstTierText: '',
    secondTierText: '',
    distributionText: '',
    themeRows: [],
    singletonText: '',
    codeThemeMap: {},
  };

  let section = '';
  for (const line of lines) {
    if (line.startsWith('第一梯隊：')) {
      result.firstTierText = line.replace('第一梯隊：', '').trim();
      section = '';
      continue;
    }
    if (line.startsWith('次主軸：')) {
      result.secondTierText = line.replace('次主軸：', '').trim();
      section = '';
      continue;
    }
    if (line === '族群分布：') {
      section = 'distribution';
      continue;
    }
    if (line === '單兵題材股：') {
      section = 'singleton';
      continue;
    }
    if (line === '量比前段班：' || line === '成交量前段班：') {
      section = '';
      continue;
    }

    if (section === 'distribution' && line.startsWith('- ')) {
      const match = line.match(/^-\s+(.+?):\s+(\d+)\s+檔\s+\|\s+(?:均量比|均成交量)=([\d.]+)(?:張)?\s+\|\s+成員=(.+)$/);
      if (!match) continue;
      const themeName = match[1].trim();
      const count = Number(match[2]);
      const members = match[4].trim().split(/\s*,\s*/).map((item) => item.trim()).filter(Boolean);
      members.forEach((member) => {
        const codeMatch = member.match(/^(\d{4,6})\b/);
        if (codeMatch) result.codeThemeMap[codeMatch[1]] = themeName;
      });
      result.themeRows.push({ themeName, count, avgVolumeRatio: Number(match[3]), members });
      continue;
    }

    if (section === 'singleton' && line.startsWith('- ')) {
      const item = line.replace(/^-\s+/, '');
      result.singletonText = result.singletonText ? `${result.singletonText}；${item}` : item;
    }
  }

  result.distributionText = result.themeRows.map((row) => `${row.themeName} ${row.count}檔`).join('、');
  return result;
}

function enrichMaBullishStocks(stocks, sector) {
  if (!sector || !sector.themeRows.length) {
    return stocks.map((stock, index) => ({ ...stock, themeName: '', _originalIndex: index }));
  }

  const orderMap = new Map(sector.themeRows.map((row, index) => [row.themeName, index]));
  return stocks
    .map((stock, index) => ({
      ...stock,
      themeName: sector.codeThemeMap[stock.code] || '單兵',
      _originalIndex: index,
    }))
    .sort((a, b) => {
      const aOrder = orderMap.has(a.themeName) ? orderMap.get(a.themeName) : Number.MAX_SAFE_INTEGER;
      const bOrder = orderMap.has(b.themeName) ? orderMap.get(b.themeName) : Number.MAX_SAFE_INTEGER;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return a._originalIndex - b._originalIndex;
    });
}

function sortStocksByRankScore(stocks) {
  return [...stocks].sort((a, b) => {
    const aScore = Number(a.rankScore || 0);
    const bScore = Number(b.rankScore || 0);
    if (aScore !== bScore) return bScore - aScore;
    return (a._originalIndex || 0) - (b._originalIndex || 0);
  });
}

function renderPlainOutput(text, tone = 'normal') {
  elements.latestOutput.className = `output-box plain-output ${tone}`;
  elements.latestOutput.innerHTML = `<pre>${escapeHtml(text || '(無輸出)')}</pre>`;
}

function setBacktestStatus(text, tone = 'neutral') {
  elements.backtestStatusPill.textContent = text;
  elements.backtestStatusPill.className = `status-pill ${tone}`;
}

function formatSignedPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const sign = number > 0 ? '+' : '';
  return `${sign}${number.toFixed(3)}%`;
}

function formatMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return number.toLocaleString('zh-TW', { maximumFractionDigits: 2 });
}

function renderBacktestEmpty(message = '標準選股 / 保守選股可在這裡直接回測。') {
  elements.backtestMeta.innerHTML = '';
  elements.backtestOutput.className = 'output-box empty';
  elements.backtestOutput.innerHTML = escapeHtml(message);
}

function syncBacktestInputsFromDates() {
  if (!state.dates.length) return;
  const earliest = state.dates[state.dates.length - 1];
  const latest = state.dates[0];
  if (!elements.backtestStartDate.value) {
    elements.backtestStartDate.value = toInputDate(earliest);
  }
  if (!elements.backtestEndDate.value) {
    elements.backtestEndDate.value = toInputDate(latest);
  }
  elements.backtestStartDate.min = toInputDate(earliest);
  elements.backtestStartDate.max = toInputDate(latest);
  elements.backtestEndDate.min = toInputDate(earliest);
  elements.backtestEndDate.max = toInputDate(latest);
}

function renderBacktest(payload) {
  state.backtestResult = payload;
  elements.backtestMeta.innerHTML = '';

  const metaItems = [
    ['策略', payload.function_name],
    ['回測區間', `${formatYmd(payload.params.start_date)} ～ ${formatYmd(payload.params.end_date)}`],
    ['停利 / 停損', `${payload.params.take_profit_pct}% / ${payload.params.stop_loss_pct}%`],
    ['買進條件', `隔日收盤 ${payload.params.entry_min_pct}% ～ +${payload.params.entry_max_pct}%`],
    ['篩選條件', `${payload.params.grade_filter} 級、前 ${payload.params.top_n} 名、${payload.params.position_size_label}、最多 ${payload.params.max_hold_days} 天`],
  ];
  for (const [label, value] of metaItems) {
    const div = document.createElement('div');
    div.className = 'meta-item';
    div.textContent = `${label}：${value}`;
    elements.backtestMeta.appendChild(div);
  }

  const summary = payload.summary || {};
  const bestRows = (payload.best_trades || []).slice(0, 5).map((trade) => `
    <tr>
      <td>${escapeHtml(trade.code)}</td>
      <td>${escapeHtml(trade.name)}</td>
      <td>${formatYmd(trade.entry_date)}</td>
      <td class="${Number(trade.ret_pct) >= 0 ? 'up-text' : 'down-text'}">${formatSignedPercent(trade.ret_pct)}</td>
      <td class="${Number(trade.pnl) >= 0 ? 'up-text' : 'down-text'}">${formatMoney(trade.pnl)}</td>
    </tr>`).join('');
  const worstRows = (payload.worst_trades || []).slice(0, 5).map((trade) => `
    <tr>
      <td>${escapeHtml(trade.code)}</td>
      <td>${escapeHtml(trade.name)}</td>
      <td>${formatYmd(trade.entry_date)}</td>
      <td class="${Number(trade.ret_pct) >= 0 ? 'up-text' : 'down-text'}">${formatSignedPercent(trade.ret_pct)}</td>
      <td class="${Number(trade.pnl) >= 0 ? 'up-text' : 'down-text'}">${formatMoney(trade.pnl)}</td>
    </tr>`).join('');

  elements.backtestOutput.className = 'output-box rich-output';
  elements.backtestOutput.innerHTML = `
    <div class="backtest-summary-grid">
      <div class="backtest-summary-card"><span>累計損益</span><strong class="${Number(summary.net_pnl_ntd) >= 0 ? 'up-text' : 'down-text'}">${formatMoney(summary.net_pnl_ntd)}</strong></div>
      <div class="backtest-summary-card"><span>報酬率</span><strong class="${Number(summary.aggregate_roi_pct) >= 0 ? 'up-text' : 'down-text'}">${formatSignedPercent(summary.aggregate_roi_pct)}</strong></div>
      <div class="backtest-summary-card"><span>勝率</span><strong>${formatSignedPercent(summary.win_rate_pct).replace('+', '')}</strong></div>
      <div class="backtest-summary-card"><span>最大回撤</span><strong class="down-text">${formatMoney(summary.max_drawdown_ntd)}</strong></div>
      <div class="backtest-summary-card"><span>成交筆數</span><strong>${escapeHtml(summary.trade_count)}</strong></div>
      <div class="backtest-summary-card"><span>總候選數</span><strong>${escapeHtml(summary.selection_total_candidates)}</strong></div>
      <div class="backtest-summary-card"><span>Profit Factor</span><strong>${summary.profit_factor ?? '—'}</strong></div>
      <div class="backtest-summary-card"><span>平均持有</span><strong>${summary.avg_holding_days} 天</strong></div>
    </div>

    <h4 class="backtest-section-title">最佳 5 筆</h4>
    <div class="backtest-table-wrap">
      <table class="backtest-table">
        <thead><tr><th>代號</th><th>名稱</th><th>進場日</th><th>報酬率</th><th>損益</th></tr></thead>
        <tbody>${bestRows || '<tr><td colspan="5">—</td></tr>'}</tbody>
      </table>
    </div>

    <h4 class="backtest-section-title">最差 5 筆</h4>
    <div class="backtest-table-wrap">
      <table class="backtest-table">
        <thead><tr><th>代號</th><th>名稱</th><th>進場日</th><th>報酬率</th><th>損益</th></tr></thead>
        <tbody>${worstRows || '<tr><td colspan="5">—</td></tr>'}</tbody>
      </table>
    </div>`;

  setBacktestStatus('回測完成', 'success');
}

function fearGreedToneClass(rating) {
  const normalized = String(rating || '').toLowerCase();
  if (normalized.includes('extreme fear') || normalized === 'fear') return 'fear';
  if (normalized === 'neutral') return 'neutral';
  if (normalized.includes('greed')) return 'greed';
  return 'neutral';
}

function fearGreedActionTone(action) {
  if (action === 'buy') return 'fear';
  if (action === 'sell') return 'greed';
  return 'neutral';
}

function formatFearGreedScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return number % 1 === 0 ? String(number) : number.toFixed(2);
}

function buildFearGreedChart(payload) {
  const points = Array.isArray(payload.one_year_history) ? payload.one_year_history : [];
  if (!points.length) {
    return '<div class="fear-greed-chart-empty">目前抓不到 1 年歷史線圖，先顯示摘要資料。</div>';
  }

  const width = 960;
  const height = 320;
  const padding = { top: 20, right: 20, bottom: 42, left: 42 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const step = points.length > 1 ? plotWidth / (points.length - 1) : 0;
  const xAt = (index) => padding.left + index * step;
  const yAt = (score) => padding.top + ((100 - Number(score)) / 100) * plotHeight;
  const linePoints = points.map((item, index) => `${xAt(index).toFixed(2)},${yAt(item.score).toFixed(2)}`).join(' ');
  const thresholdLines = [75, 50, 25].map((level) => {
    const y = yAt(level).toFixed(2);
    const cls = level === 75 ? 'sell' : level === 25 ? 'buy' : 'neutral';
    return `
      <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="threshold-line ${cls}" />
      <text x="8" y="${Number(y) + 4}" class="threshold-label">${level}</text>
    `;
  }).join('');
  const tickIndexes = [0, Math.floor((points.length - 1) * 0.25), Math.floor((points.length - 1) * 0.5), Math.floor((points.length - 1) * 0.75), points.length - 1]
    .filter((value, index, arr) => arr.indexOf(value) === index);
  const ticks = tickIndexes.map((index) => {
    const x = xAt(index).toFixed(2);
    const label = (points[index].date || '').slice(5).replace('-', '/');
    return `<text x="${x}" y="${height - 10}" text-anchor="middle" class="axis-label">${escapeHtml(label)}</text>`;
  }).join('');
  const latest = points[points.length - 1];
  const latestX = xAt(points.length - 1).toFixed(2);
  const latestY = yAt(latest.score).toFixed(2);
  const chartLabel = `${payload.market_label || payload.source || '恐懼與貪婪指數'}過去一年走勢圖`;

  return `
    <div class="fear-greed-chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" class="fear-greed-chart" role="img" aria-label="${escapeHtml(chartLabel)}">
        <rect x="0" y="0" width="${width}" height="${height}" rx="18" ry="18" class="chart-bg"></rect>
        ${thresholdLines}
        <polyline points="${linePoints}" class="history-line"></polyline>
        <circle cx="${latestX}" cy="${latestY}" r="5" class="history-dot"></circle>
        <text x="${latestX}" y="${Math.max(18, Number(latestY) - 10)}" text-anchor="end" class="latest-label">最新 ${escapeHtml(formatFearGreedScore(latest.score))}</text>
        ${ticks}
      </svg>
      <div class="fear-greed-chart-legend">
        <span><i class="legend-swatch line"></i>過去 1 年指數</span>
        <span><i class="legend-swatch buy"></i>25 以下：偏低，可留意買點</span>
        <span><i class="legend-swatch sell"></i>75 以上：偏熱，可留意賣點</span>
      </div>
    </div>
  `;
}

function renderFearGreedMarket(payload) {
  const sourceHtml = payload.source_url
    ? `<a href="${escapeHtml(payload.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(payload.source || '來源連結')}</a>`
    : escapeHtml(payload.source || '—');
  const metaHtml = `
    <div class="fear-greed-market-meta">
      <span>來源：${sourceHtml}</span>
      <span>更新：${escapeHtml(payload.updated_at || '—')}</span>
    </div>
  `;

  if (!payload.available) {
    const linkHtml = payload.source_url
      ? `<a class="fear-greed-link-button" href="${escapeHtml(payload.source_url)}" target="_blank" rel="noopener noreferrer">前往 MacroMicro 查看</a>`
      : '';
    return `
      <section class="fear-greed-market-card unavailable">
        <div class="fear-greed-market-header">
          <div>
            <div class="fear-greed-market-title">${escapeHtml(payload.market_label || payload.source || '情緒指數')}</div>
            ${metaHtml}
          </div>
        </div>
        <div class="fear-greed-chart-empty">${escapeHtml(payload.error_message || '目前暫時抓不到資料。')}</div>
        ${linkHtml}
      </section>
    `;
  }

  const recommendation = payload.recommendation || { action: 'hold', label: '觀察', message: '—' };
  const historyCards = (payload.history || []).map((item) => `
    <div class="fear-greed-mini-card ${fearGreedToneClass(item.rating || '')}">
      <div class="fear-greed-mini-label">${escapeHtml(item.label)}</div>
      <div class="fear-greed-mini-score">${escapeHtml(formatFearGreedScore(item.score))}</div>
    </div>
  `).join('');

  return `
    <section class="fear-greed-market-card">
      <div class="fear-greed-market-header">
        <div>
          <div class="fear-greed-market-title">${escapeHtml(payload.market_label || payload.source || '情緒指數')}</div>
          ${metaHtml}
        </div>
      </div>

      <section class="fear-greed-summary ${fearGreedToneClass(payload.rating)}">
        <div class="fear-greed-score-wrap">
          <div class="fear-greed-score">${escapeHtml(formatFearGreedScore(payload.score))}</div>
          <div class="fear-greed-rating">${escapeHtml(payload.rating || '—')}</div>
        </div>
        <div class="fear-greed-summary-text">
          <div class="fear-greed-headline">${escapeHtml(payload.status_text || '')}</div>
          <div class="fear-greed-subtitle">只看過去 1 年走勢，並用 25 / 75 當作判讀區間。</div>
        </div>
      </section>

      <section class="fear-greed-advice ${fearGreedActionTone(recommendation.action)}">
        <div class="fear-greed-advice-title">操作提醒：${escapeHtml(recommendation.label)}</div>
        <div class="fear-greed-advice-text">${escapeHtml(recommendation.message)}</div>
      </section>

      <section class="fear-greed-history-panel">
        <div class="fear-greed-panel-title">過去 1 年指數走勢</div>
        ${buildFearGreedChart(payload)}
      </section>

      <section class="fear-greed-history-grid">${historyCards}</section>
    </section>
  `;
}

function renderFearGreed(payload) {
  state.currentRun = null;
  state.fearGreed = payload;
  elements.latestMeta.innerHTML = '';
  elements.artifactList.innerHTML = '';

  const metaItems = [
    ['資料頁', '美國 + 台灣'],
    ['抓取時間', compactTimestamp(payload.fetched_at)],
    ['快取', payload.from_cache ? '是' : '否'],
  ];
  for (const [label, value] of metaItems) {
    const div = document.createElement('div');
    div.className = 'meta-item';
    div.textContent = `${label}：${value}`;
    elements.latestMeta.appendChild(div);
  }

  const markets = Array.isArray(payload.markets) ? payload.markets : [];
  elements.latestOutput.className = 'output-box fear-greed-output';
  elements.latestOutput.innerHTML = `
    <div class="fear-greed-page-title">同頁查看美國 CNN 與台灣 MM 的恐懼與貪婪指數，圖表都只顯示 1 年內範圍。</div>
    <div class="fear-greed-market-grid">${markets.map(renderFearGreedMarket).join('')}</div>
  `;

  const hasUnavailable = markets.some((item) => item && item.available === false);
  setStatus(hasUnavailable ? '部分情緒資料已更新' : (payload.from_cache ? '已載入情緒快取' : '情緒指數已更新'), hasUnavailable ? 'running' : 'success');
}

function gradeTone(grade) {
  if (grade === 'A') return 'grade-a';
  if (grade === 'B') return 'grade-b';
  return 'grade-c';
}

function buildSummaryChips(summary) {
  return Object.entries(summary)
    .filter(([, value]) => value)
    .map(([label, value]) => `<div class="summary-chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join('');
}

function renderLimitUp(parsed) {
  const enrichedStocks = enrichMaBullishStocks(parsed.stocks, parsed.sector);
  const stocks = sortStocksByRankScore(enrichedStocks);
  const intradayMap = getIntradayMap();
  const intradaySummary = state.currentRun?.intraday?.payload;
  const showIntradayColumns = isIntradayFunction();

  if (!stocks.length) {
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = `
      <div class="summary-grid">${buildSummaryChips({
        '比較區間': parsed.summary.range,
        '入選數量': parsed.summary.count,
        '即時行情': showIntradayColumns ? (state.marketState?.market_open ? '尚未查詢' : '盤後停用') : '',
      })}</div>
      <div class="empty-block">沒有可顯示的股票。</div>`;
    return;
  }

  const maxFutureDays = Math.max(...stocks.map((s) => s.futureDays.length));
  const extraIntradayColumns = showIntradayColumns ? 2 : 0;
  const totalColumns = (parsed.sector ? 1 : 0) + 6 + extraIntradayColumns + (maxFutureDays > 0 ? maxFutureDays + 1 : 0);
  const intradayStatus = showIntradayColumns
    ? (intradaySummary
        ? `${intradaySummary.success_count}/${intradaySummary.count}｜${compactTimestamp(intradaySummary.finished_at)}`
        : (state.marketState?.market_open ? '尚未查詢' : '盤後停用'))
    : '';

  let html = `<div class="summary-grid">${buildSummaryChips({
    '比較區間': parsed.summary.range,
    '參考前日': parsed.summary.referenceDate,
    '入選數量': parsed.summary.count,
    '即時行情': intradayStatus,
  })}</div>`;
  html += '<div class="table-wrapper"><table class="stock-table"><thead><tr>';
  if (parsed.sector) {
    html += '<th>族群</th>';
  }
  html += '<th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th>名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">收盤</th><th style="text-align:right">成交量</th>';
  if (showIntradayColumns) {
    html += '<th style="text-align:center">即時價</th><th style="text-align:right">即時量</th>';
  }

  if (maxFutureDays > 0 && stocks[0].futureDays.length > 0) {
    for (const day of stocks[0].futureDays) {
      html += `<th style="text-align:center">${escapeHtml(formatYmd(day.date).slice(5))}</th>`;
    }
    html += '<th style="text-align:center">合計%</th>';
  }
  html += '</tr></thead><tbody>';

  for (const stock of stocks) {
    const intraday = intradayMap[stock.code] || {};
    html += '<tr>';
    if (parsed.sector) {
      html += `<td class="td-theme"><span class="theme-pill">${escapeHtml(stock.themeName || '—')}</span></td>`;
    }
    html += `<td class="td-number td-score">${escapeHtml(stock.rankScore || '—')}</td>`;
    html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
    html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
    html += buildInlineKlineSlot(stock);
    html += `<td class="td-number">${escapeHtml(stock.close)}</td>`;
    html += `<td class="td-number">${escapeHtml(stock.volume)}</td>`;
    if (showIntradayColumns) {
      const intradayTone = toneClassFromNumber(intraday.change_percent);
      const intradayCellClass = intraday.error ? 'td-future td-empty' : `td-future td-intraday ${intradayTone}`;
      const intradayPrice = intraday.error ? '—' : formatPrice(intraday.last_price);
      const intradayChange = intraday.error ? '' : formatChangePercent(intraday.change_percent);
      html += `<td class="${intradayCellClass}"><strong>${intradayPrice}</strong>${intraday.error ? '' : `<span class="${intradayTone}">${escapeHtml(intradayChange)}</span>`}</td>`;
      html += `<td class="td-number">${intraday.error ? '—' : formatVolume(intraday.trade_volume)}</td>`;
    }

    if (maxFutureDays > 0) {
      for (const day of stock.futureDays) {
        const prevCls = day.pctFromPrev.startsWith('+') ? 'up-text' : day.pctFromPrev.startsWith('-') ? 'down-text' : '';
        html += `<td class="td-future"><strong>${escapeHtml(day.close)}</strong>`;
        html += `<span class="${prevCls}">${escapeHtml(day.pctFromPrev)}</span></td>`;
      }
      const lastDay = stock.futureDays[stock.futureDays.length - 1];
      if (lastDay) {
        const signalCls = lastDay.pctFromSignal.startsWith('+') ? 'up-text' : lastDay.pctFromSignal.startsWith('-') ? 'down-text' : '';
        html += `<td class="td-future td-total"><span class="${signalCls}">${escapeHtml(lastDay.pctFromSignal)}</span></td>`;
      } else {
        html += '<td class="td-future td-empty">—</td>';
      }
      for (let i = stock.futureDays.length; i < maxFutureDays; i++) {
        html += '<td class="td-future td-empty">—</td>';
      }
    }

    html += '</tr>';
  }

  html += '</tbody></table></div>';

  elements.latestOutput.className = 'output-box rich-output';
  elements.latestOutput.innerHTML = html;
  hydrateInlineKlines(stocks);
}

function renderPreBreakout(parsed) {
  const stocks = parsed.stocks;
  const institutionalMap = getInstitutionalMap();
  const institutionalSummary = state.currentRun?.institutional?.payload;
  const intradayMap = getIntradayMap();
  const intradaySummary = state.currentRun?.intraday?.payload;
  const showIntradayColumns = isIntradayFunction();

  if (!stocks.length) {
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = `
      <div class="summary-grid">${buildSummaryChips({ '交易日': parsed.summary.date, '市場熱度': parsed.summary.heat, '入選數量': parsed.summary.count })}</div>
      <div class="empty-block">沒有可顯示的股票。</div>`;
    return;
  }

  const maxFutureDays = Math.max(...stocks.map((s) => s.futureDays.length));
  const intradayStatus = showIntradayColumns
    ? (intradaySummary
        ? `${intradaySummary.success_count}/${intradaySummary.count}｜${compactTimestamp(intradaySummary.finished_at)}`
        : (state.marketState?.market_open ? '尚未查詢' : '盤後停用'))
    : '';

  let html = `<div class="summary-grid">${buildSummaryChips({
    '交易日': parsed.summary.date,
    '市場熱度': parsed.summary.heat,
    '入選數量': parsed.summary.count,
    '法人狀態': institutionalSummary ? `${institutionalSummary.success_count}/${institutionalSummary.count}` : '尚未查詢',
    '即時行情': intradayStatus,
  })}</div>`;
  html += '<div class="table-wrapper"><table class="stock-table"><thead><tr>';
  html += '<th>等級</th><th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th class="th-name" style="text-align:left">名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">收盤</th><th style="text-align:right">成交量</th>';
  if (showIntradayColumns) {
    html += '<th style="text-align:center">即時價</th><th style="text-align:right">即時量</th>';
  }
  html += '<th style="text-align:right">法人合計</th>';

  if (maxFutureDays > 0 && stocks[0].futureDays.length > 0) {
    for (const day of stocks[0].futureDays) {
      html += `<th style="text-align:center">${escapeHtml(formatYmd(day.date).slice(5))}</th>`;
    }
    html += '<th style="text-align:center">合計%</th>';
  }
  html += '</tr></thead><tbody>';

  for (const stock of stocks) {
    const tone = gradeTone(stock.grade);
    const inst = institutionalMap[stock.code] || {};
    const intraday = intradayMap[stock.code] || {};
    html += '<tr>';
    html += `<td class="td-grade"><span class="grade-pill ${tone}">${escapeHtml(stock.grade)}</span></td>`;
    html += `<td class="td-number td-score">${escapeHtml(stock.rankScore || '—')}</td>`;
    html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
    html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
    html += buildInlineKlineSlot(stock);
    html += `<td class="td-number">${escapeHtml(stock.close)}</td>`;
    html += `<td class="td-number">${escapeHtml(stock.volume)}</td>`;
    if (showIntradayColumns) {
      const intradayTone = toneClassFromNumber(intraday.change_percent);
      const intradayCellClass = intraday.error ? 'td-future td-empty' : `td-future td-intraday ${intradayTone}`;
      const intradayPrice = intraday.error ? '—' : formatPrice(intraday.last_price);
      const intradayChange = intraday.error ? '' : formatChangePercent(intraday.change_percent);
      html += `<td class="${intradayCellClass}"><strong>${intradayPrice}</strong>${intraday.error ? '' : `<span class="${intradayTone}">${escapeHtml(intradayChange)}</span>`}</td>`;
      html += `<td class="td-number">${intraday.error ? '—' : formatVolume(intraday.trade_volume)}</td>`;
    }
    html += `<td class="td-number td-inst-total">${formatPrice(inst.total)}</td>`;

    if (maxFutureDays > 0) {
      for (const day of stock.futureDays) {
        const prevCls = day.pctFromPrev.startsWith('+') ? 'up-text' : day.pctFromPrev.startsWith('-') ? 'down-text' : '';
        html += `<td class="td-future"><strong>${escapeHtml(day.close)}</strong>`;
        html += `<span class="${prevCls}">${escapeHtml(day.pctFromPrev)}</span></td>`;
      }
      const lastDay = stock.futureDays[stock.futureDays.length - 1];
      if (lastDay) {
        const signalCls = lastDay.pctFromSignal.startsWith('+') ? 'up-text' : lastDay.pctFromSignal.startsWith('-') ? 'down-text' : '';
        html += `<td class="td-future td-total"><span class="${signalCls}">${escapeHtml(lastDay.pctFromSignal)}</span></td>`;
      } else {
        html += '<td class="td-future td-empty">—</td>';
      }
      for (let i = stock.futureDays.length; i < maxFutureDays; i++) {
        html += '<td class="td-future td-empty">—</td>';
      }
    }

    html += '</tr>';
  }

  html += '</tbody></table></div>';

  elements.latestOutput.className = 'output-box rich-output';
  elements.latestOutput.innerHTML = html;
  hydrateInlineKlines(stocks);
}

function renderMaBullish(parsed) {
  const stocks = enrichMaBullishStocks(parsed.stocks, parsed.sector);
  const intradayMap = getIntradayMap();
  const intradaySummary = state.currentRun?.intraday?.payload;
  const showIntradayColumns = isIntradayFunction();
  if (!stocks.length) {
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = `
      <div class="summary-grid">${buildSummaryChips({
        '比較區間': parsed.summary.range,
        '入選數量': parsed.summary.count,
        '型態': 'MA5 > MA10 > MA20 新成形',
        '即時行情': showIntradayColumns ? (state.marketState?.market_open ? '尚未查詢' : '盤後停用') : '',
      })}</div>
      <div class="empty-block">沒有可顯示的股票。</div>`;
    return;
  }

  const maxFutureDays = Math.max(...stocks.map((s) => s.futureDays.length));
  const extraIntradayColumns = showIntradayColumns ? 2 : 0;
  const totalColumns = 8 + extraIntradayColumns + (maxFutureDays > 0 ? maxFutureDays + 1 : 0);
  const intradayStatus = showIntradayColumns
    ? (intradaySummary
        ? `${intradaySummary.success_count}/${intradaySummary.count}｜${compactTimestamp(intradaySummary.finished_at)}`
        : (state.marketState?.market_open ? '尚未查詢' : '盤後停用'))
    : '';

  let html = `<div class="summary-grid">${buildSummaryChips({
    '比較區間': parsed.summary.range,
    '入選數量': parsed.summary.count,
    '型態': 'MA5 > MA10 > MA20 新成形',
    '即時行情': intradayStatus,
  })}</div>`;
  html += '<div class="table-wrapper"><table class="stock-table"><thead><tr>';
  html += '<th>族群</th><th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th>名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">收盤</th><th style="text-align:right">成交量</th><th style="text-align:right">量能倍數</th>';
  if (showIntradayColumns) {
    html += '<th style="text-align:center">即時價</th><th style="text-align:right">即時量</th>';
  }

  if (maxFutureDays > 0 && stocks[0].futureDays.length > 0) {
    for (const day of stocks[0].futureDays) {
      html += `<th style="text-align:center">${escapeHtml(formatYmd(day.date).slice(5))}</th>`;
    }
    html += '<th style="text-align:center">合計%</th>';
  }
  html += '</tr></thead><tbody>';

  let currentTheme = null;
  for (const stock of stocks) {
    const intraday = intradayMap[stock.code] || {};
    if (stock.themeName && stock.themeName !== currentTheme) {
      currentTheme = stock.themeName;
      const themeMeta = parsed.sector?.themeRows?.find((row) => row.themeName === stock.themeName);
      const themeLabel = themeMeta ? `${themeMeta.themeName}｜${themeMeta.count} 檔` : stock.themeName;
      html += `<tr class="group-divider-row"><td colspan="${totalColumns}"><div class="group-divider-label">${escapeHtml(themeLabel)}</div></td></tr>`;
    }

    html += '<tr>';
    html += `<td class="td-theme"><span class="theme-pill">${escapeHtml(stock.themeName || '—')}</span></td>`;
    html += `<td class="td-number td-score">${escapeHtml(stock.rankScore || '—')}</td>`;
    html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
    html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
    html += buildInlineKlineSlot(stock);
    html += `<td class="td-number">${escapeHtml(stock.close)}</td>`;
    html += `<td class="td-number">${escapeHtml(stock.volume)}</td>`;
    html += `<td class="td-number up-text">${escapeHtml(stock.multiple)}倍</td>`;
    if (showIntradayColumns) {
      const intradayTone = toneClassFromNumber(intraday.change_percent);
      const intradayCellClass = intraday.error ? 'td-future td-empty' : `td-future td-intraday ${intradayTone}`;
      const intradayPrice = intraday.error ? '—' : formatPrice(intraday.last_price);
      const intradayChange = intraday.error ? '' : formatChangePercent(intraday.change_percent);
      html += `<td class="${intradayCellClass}"><strong>${intradayPrice}</strong>${intraday.error ? '' : `<span class="${intradayTone}">${escapeHtml(intradayChange)}</span>`}</td>`;
      html += `<td class="td-number">${intraday.error ? '—' : formatVolume(intraday.trade_volume)}</td>`;
    }

    if (maxFutureDays > 0) {
      for (const day of stock.futureDays) {
        const prevCls = day.pctFromPrev.startsWith('+') ? 'up-text' : day.pctFromPrev.startsWith('-') ? 'down-text' : '';
        html += `<td class="td-future"><strong>${escapeHtml(day.close)}</strong>`;
        html += `<span class="${prevCls}">${escapeHtml(day.pctFromPrev)}</span></td>`;
      }
      const lastDay = stock.futureDays[stock.futureDays.length - 1];
      if (lastDay) {
        const signalCls = lastDay.pctFromSignal.startsWith('+') ? 'up-text' : lastDay.pctFromSignal.startsWith('-') ? 'down-text' : '';
        html += `<td class="td-future td-total"><span class="${signalCls}">${escapeHtml(lastDay.pctFromSignal)}</span></td>`;
      } else {
        html += '<td class="td-future td-empty">—</td>';
      }
      for (let i = stock.futureDays.length; i < maxFutureDays; i++) {
        html += '<td class="td-future td-empty">—</td>';
      }
    }

    html += '</tr>';
  }

  html += '</tbody></table></div>';

  if (parsed.sector) {
    html += '<div class="sector-brief-card">';
    html += '<h3>族群快速分類摘要</h3>';
    html += '<ul class="sector-brief-list">';
    if (parsed.sector.firstTierText) html += `<li><strong>第一梯隊：</strong>${escapeHtml(parsed.sector.firstTierText)}</li>`;
    if (parsed.sector.secondTierText) html += `<li><strong>次主軸：</strong>${escapeHtml(parsed.sector.secondTierText)}</li>`;
    if (parsed.sector.distributionText) html += `<li><strong>族群分布：</strong>${escapeHtml(parsed.sector.distributionText)}</li>`;
    if (parsed.sector.singletonText) html += `<li><strong>單兵：</strong>${escapeHtml(parsed.sector.singletonText)}</li>`;
    html += '</ul></div>';
  }

  elements.latestOutput.className = 'output-box rich-output';
  elements.latestOutput.innerHTML = html;
  hydrateInlineKlines(stocks);
}

function renderOutput(run) {
  const text = run.output_text || '(無輸出)';
  const parsedLimitUp = parseLimitUpOutput(text);
  if (parsedLimitUp && run.status === 'success') {
    renderLimitUp(parsedLimitUp);
    return;
  }

  const parsedPreBreakout = parsePreBreakoutOutput(text);
  if (parsedPreBreakout && run.status === 'success') {
    renderPreBreakout(parsedPreBreakout);
    return;
  }

  const parsedMaBullish = parseMaBullishOutput(text);
  if (parsedMaBullish && run.status === 'success') {
    renderMaBullish(parsedMaBullish);
    return;
  }

  renderPlainOutput(text, run.status === 'failed' ? 'error-output' : 'normal-output');
}

function renderLatest(run) {
  state.currentRun = run || null;
  elements.latestMeta.innerHTML = '';
  elements.artifactList.innerHTML = '';
  renderActionButtons();

  if (!run) {
    elements.latestOutput.className = 'output-box empty';
    elements.latestOutput.innerHTML = '這個日期目前還沒有執行紀錄，主人可以直接按執行。';
    setStatus('尚未執行', 'neutral');
    return;
  }

  renderOutput(run);
  setStatus(run.status === 'success' ? (run.from_cache ? '已載入快取' : '執行完成') : '執行失敗', statusTone(run.status));

  const metaItems = [
    ['交易日', formatYmd(run.result_date || state.selectedDate)],
    ['執行時間', compactTimestamp(run.started_at)],
    ['完成時間', compactTimestamp(run.finished_at)],
    ['耗時', formatDuration(run.duration_seconds)],
    ['狀態', run.status === 'success' ? '成功' : '失敗'],
  ];
  if (run.from_cache) {
    metaItems.push(['資料來源', 'DB 快取']);
    metaItems.push(['快取時間', compactTimestamp(run.cached_at)]);
  }

  for (const [label, value] of metaItems) {
    const div = document.createElement('div');
    div.className = 'meta-item';
    div.textContent = `${label}：${value}`;
    elements.latestMeta.appendChild(div);
  }
}

async function refreshMarketState() {
  try {
    const response = await fetch('/api/market_state');
    const payload = await response.json();
    if (response.ok) {
      state.marketState = payload;
    }
  } catch (error) {
    // ignore market-state refresh errors and keep previous state
  }
}

async function loadCurrentResult() {
  if (!state.selectedDate) {
    elements.latestOutput.className = 'output-box empty';
    elements.latestOutput.innerHTML = '目前沒有可選日期。';
    setStatus('待命', 'neutral');
    return;
  }

  await refreshMarketState();

  const query = new URLSearchParams({
    function_key: state.selectedKey,
    result_date: state.selectedDate,
  });
  const response = await fetch(`/api/result?${query.toString()}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || '讀取結果失敗');
  }
  renderLatest(payload);
}

async function loadFearGreedStatus(forceRefresh = false) {
  setStatus(forceRefresh ? '重新抓取情緒指數中...' : '載入情緒指數中...', 'running');
  elements.latestMeta.innerHTML = '';
  elements.artifactList.innerHTML = '';
  elements.latestOutput.className = 'output-box empty';
  elements.latestOutput.innerHTML = forceRefresh
    ? '正在重新抓取美國 / 台灣恐懼與貪婪指數，請稍候...'
    : '正在載入美國 / 台灣恐懼與貪婪指數，請稍候...';

  const query = new URLSearchParams();
  if (forceRefresh) query.set('force_refresh', '1');
  const response = await fetch(`/api/fear_greed?${query.toString()}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || '讀取美國 / 台灣恐懼與貪婪指數失敗');
  }
  renderFearGreed(payload);
}

async function refreshCurrentView() {
  if (isFearGreedFunction()) {
    await loadFearGreedStatus(true);
    return;
  }
  await loadCurrentResult();
}

async function runBacktest() {
  if (!isBacktestFunction()) return;
  const startDate = fromInputDate(elements.backtestStartDate.value);
  const endDate = fromInputDate(elements.backtestEndDate.value);
  const takeProfitPct = Number(elements.backtestTp.value);
  const stopLossPct = Number(elements.backtestSl.value);
  const entryMaxPct = Number(elements.backtestEntryMax.value);
  const entryMinPct = Number(elements.backtestEntryMin.value);
  const topN = Number(elements.backtestTopN.value);

  if (!startDate || !endDate) {
    renderBacktestEmpty('請先填入開始與結束日期。');
    setBacktestStatus('缺少日期', 'failed');
    return;
  }
  if (startDate > endDate) {
    renderBacktestEmpty('開始日期不可晚於結束日期。');
    setBacktestStatus('日期錯誤', 'failed');
    return;
  }
  if (!Number.isFinite(takeProfitPct) || takeProfitPct <= 0 || !Number.isFinite(stopLossPct) || stopLossPct <= 0) {
    renderBacktestEmpty('停利 / 停損請輸入大於 0 的數字。');
    setBacktestStatus('參數錯誤', 'failed');
    return;
  }
  if (!Number.isFinite(entryMaxPct) || !Number.isFinite(entryMinPct)) {
    renderBacktestEmpty('隔日收盤上下限 % 請輸入數字。');
    setBacktestStatus('參數錯誤', 'failed');
    return;
  }
  if (entryMinPct > entryMaxPct) {
    renderBacktestEmpty('買進下限不可大於上限。');
    setBacktestStatus('參數錯誤', 'failed');
    return;
  }
  if (!Number.isInteger(topN) || topN <= 0) {
    renderBacktestEmpty('A級前幾名請輸入大於 0 的整數。');
    setBacktestStatus('參數錯誤', 'failed');
    return;
  }

  elements.backtestRunButton.disabled = true;
  setBacktestStatus('回測中...', 'running');
  elements.backtestOutput.className = 'output-box empty';
  elements.backtestOutput.innerHTML = '回測中，請稍候...';

  try {
    const response = await fetch(`/api/backtest/${encodeURIComponent(state.selectedKey)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start_date: startDate,
        end_date: endDate,
        take_profit_pct: takeProfitPct,
        stop_loss_pct: stopLossPct,
        entry_max_pct: entryMaxPct,
        entry_min_pct: entryMinPct,
        top_n: topN,
        max_hold_days: 5,
        shares: 1000,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || '回測失敗');
    }
    renderBacktest(payload);
  } catch (error) {
    setBacktestStatus('回測失敗', 'failed');
    renderBacktestEmpty(String(error.message || error));
  } finally {
    elements.backtestRunButton.disabled = false;
  }
}

async function runSerenityAnalysis() {
  if (!state.selectedFunction?.executable) return;
  const stocks = getCurrentSerenityStocks();
  if (!stocks.length) {
    resetSerenityPanel('目前結果沒有可分析的候選股票，請先執行選股。');
    setSerenityStatus('沒有候選股', 'failed');
    return;
  }

  const progressSteps = [
    '整理候選股與族群...',
    '搜尋產業鏈公開資料...',
    '尋找供應鏈瓶頸...',
    '比對公司證據與風險...',
    '產生研究優先順序...',
  ];
  let progressIndex = 0;
  elements.serenityButton.disabled = true;
  elements.serenityPanel.hidden = false;
  elements.serenityMeta.innerHTML = '';
  elements.serenityOutput.className = 'serenity-output serenity-loading';
  elements.serenityOutput.textContent = `${progressSteps[0]}\n深度分析通常需要數分鐘，請保持程式開啟。`;
  setSerenityStatus('分析中...', 'running');
  state.serenityProgressTimer = window.setInterval(() => {
    progressIndex = (progressIndex + 1) % progressSteps.length;
    elements.serenityOutput.textContent = `${progressSteps[progressIndex]}\n深度分析通常需要數分鐘，請保持程式開啟。`;
  }, 4000);

  try {
    const response = await fetch(`/api/serenity/${encodeURIComponent(state.selectedKey)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        result_date: state.selectedDate,
        stocks,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || 'Serenity 深度分析失敗');
    }

    state.serenityResult = payload;
    elements.serenityMeta.innerHTML = '';
    const metaItems = [
      ['選股功能', payload.function_name],
      ['交易日', formatYmd(payload.result_date)],
      ['候選股', `${payload.stock_count} 檔`],
      ['分析時間', compactTimestamp(payload.generated_at)],
      ['耗時', formatDuration(Number(payload.duration_seconds || 0))],
    ];
    for (const [label, value] of metaItems) {
      const div = document.createElement('div');
      div.className = 'meta-item';
      div.textContent = `${label}：${value}`;
      elements.serenityMeta.appendChild(div);
    }
    elements.serenityOutput.className = 'serenity-output';
    elements.serenityOutput.innerHTML = `<pre>${escapeHtml(payload.analysis || '(無分析內容)')}</pre>`;
    setSerenityStatus('分析完成', 'success');
  } catch (error) {
    elements.serenityOutput.className = 'serenity-output serenity-error';
    elements.serenityOutput.innerHTML = `<pre>${escapeHtml(String(error.message || error))}</pre>`;
    setSerenityStatus('分析失敗', 'failed');
  } finally {
    if (state.serenityProgressTimer) {
      clearInterval(state.serenityProgressTimer);
      state.serenityProgressTimer = null;
    }
    renderActionButtons();
  }
}

async function selectFunction(key) {
  state.selectedKey = key;
  localStorage.setItem('stock-control-selected', key);
  state.selectedFunction = state.functions.find((item) => item.key === key) || null;
  resetSerenityPanel();
  renderGroups();

  if (!state.selectedFunction) return;

  elements.title.textContent = state.selectedFunction.name;
  elements.description.textContent = state.selectedFunction.description;
  elements.dateInput.disabled = !state.dates.length;
  renderActionButtons();
  syncBacktestInputsFromDates();
  if (isBacktestFunction()) {
    if (!state.backtestResult || state.backtestResult.function_key !== state.selectedKey) {
      renderBacktestEmpty();
      setBacktestStatus('待命', 'neutral');
    }
  } else {
    state.backtestResult = null;
    renderBacktestEmpty('這個功能目前沒有回測面板。');
    setBacktestStatus('待命', 'neutral');
  }

  if (isFearGreedFunction()) {
    await loadFearGreedStatus();
    return;
  }

  await loadCurrentResult();
}

async function runSelectedFunction() {
  if (!state.selectedFunction?.executable) return;
  if (!state.selectedDate) {
    renderPlainOutput('目前沒有可用交易日。', 'error-output');
    setStatus('執行失敗', 'failed');
    return;
  }

  elements.runButton.disabled = true;
  setStatus('執行中', 'running');
  elements.latestOutput.className = 'output-box empty';
  elements.latestOutput.innerHTML = '執行中，請稍候...';
  elements.artifactList.innerHTML = '';

  try {
    const response = await fetch(`/api/run/${encodeURIComponent(state.selectedFunction.key)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ result_date: state.selectedDate }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || '執行失敗');
    }
    renderLatest(payload);
  } catch (error) {
    setStatus('執行失敗', 'failed');
    renderPlainOutput(String(error.message || error), 'error-output');
  } finally {
    elements.runButton.disabled = false;
  }
}

async function refreshFuture() {
  if (!state.selectedFunction?.executable) return;
  if (!state.selectedDate) {
    renderPlainOutput('目前沒有可用交易日。', 'error-output');
    return;
  }

  elements.refreshFutureButton.disabled = true;
  setStatus('強制重跑中...', 'running');
  elements.latestOutput.className = 'output-box empty';
  elements.latestOutput.innerHTML = '跳過快取強制重跑中，請稍候...';

  try {
    const response = await fetch(`/api/refresh_future/${encodeURIComponent(state.selectedFunction.key)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ result_date: state.selectedDate }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || '強制重跑失敗');
    }
    renderLatest(payload);
  } catch (error) {
    setStatus('強制重跑失敗', 'failed');
    renderPlainOutput(String(error.message || error), 'error-output');
  } finally {
    elements.refreshFutureButton.disabled = false;
  }
}

async function runInstitutional() {
  if (!isPreBreakoutFunction() || !state.selectedDate) return;
  if (!(await ensureTokenConfigured('finmind'))) return;

  elements.institutionalButton.disabled = true;
  setStatus('法人查詢中...', 'running');

  try {
    const response = await fetch(`/api/institutional/${encodeURIComponent(state.selectedFunction.key)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ result_date: state.selectedDate }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || '法人查詢失敗');
    }

    if (!state.currentRun) {
      await loadCurrentResult();
    } else {
      state.currentRun.institutional = {
        status: payload.status,
        payload: payload.payload,
        source: payload.source,
        started_at: payload.started_at,
        finished_at: payload.finished_at,
        duration_seconds: payload.duration_seconds,
        cached_at: payload.cached_at,
      };
      renderLatest(state.currentRun);
      setStatus(payload.from_cache ? '已載入法人快取' : '法人查詢完成', 'success');
    }
  } catch (error) {
    setStatus('法人查詢失敗', 'failed');
    renderPlainOutput(String(error.message || error), 'error-output');
  } finally {
    elements.institutionalButton.disabled = false;
  }
}

async function runIntraday() {
  if (!isIntradayFunction() || !state.selectedDate) return;
  if (!(await ensureTokenConfigured('fugle'))) return;

  await refreshMarketState();
  renderActionButtons();
  if (!isIntradayAvailable()) {
    setStatus('盤後停用', 'failed');
    renderPlainOutput('主人，現在不是盤中時段，即時行情功能暫不啟用。', 'error-output');
    return;
  }

  elements.intradayButton.disabled = true;
  setStatus('即時行情查詢中...', 'running');

  try {
    const response = await fetch(`/api/intraday/${encodeURIComponent(state.selectedFunction.key)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ result_date: state.selectedDate }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || '即時行情查詢失敗');
    }

    if (!state.currentRun) {
      await loadCurrentResult();
    } else {
      state.currentRun.intraday = {
        status: payload.status,
        payload: payload.payload,
        source: payload.source,
        started_at: payload.started_at,
        finished_at: payload.finished_at,
        duration_seconds: payload.duration_seconds,
      };
      renderLatest(state.currentRun);
      setStatus('即時行情更新完成', 'success');
    }
  } catch (error) {
    setStatus('即時行情失敗', 'failed');
    renderPlainOutput(String(error.message || error), 'error-output');
  } finally {
    renderActionButtons();
  }
}

async function init() {
  const [functionsResponse, datesResponse, marketStateResponse] = await Promise.all([
    fetch('/api/functions'),
    fetch('/api/dates'),
    fetch('/api/market_state'),
  ]);
  state.functions = await functionsResponse.json();
  const datePayload = await datesResponse.json();
  state.marketState = marketStateResponse.ok ? await marketStateResponse.json() : state.marketState;
  state.dates = datePayload.dates || [];
  if (datePayload.sync_status?.fetched) {
    setStatus('已自動補抓最新資料', 'success');
  } else if (datePayload.sync_status?.status === 'failed') {
    setStatus('最新資料補抓失敗', 'failed');
  }
  if (!state.selectedDate || !state.dates.includes(state.selectedDate)) {
    state.selectedDate = datePayload.latest_date || '';
    if (state.selectedDate) {
      localStorage.setItem('stock-control-date', state.selectedDate);
    }
  }
  if (!state.functions.find((item) => item.key === state.selectedKey)) {
    state.selectedKey = state.functions[0]?.key || '';
  }

  renderDateOptions();
  renderActionButtons();
  syncBacktestInputsFromDates();
  checkUpdateStatus();

  elements.refreshButton.addEventListener('click', refreshCurrentView);
  elements.serenityButton.addEventListener('click', runSerenityAnalysis);
  elements.institutionalButton.addEventListener('click', runInstitutional);
  elements.intradayButton.addEventListener('click', runIntraday);
  elements.refreshFutureButton.addEventListener('click', refreshFuture);
  elements.runButton.addEventListener('click', runSelectedFunction);
  elements.backtestRunButton.addEventListener('click', runBacktest);
  elements.settingsButton.addEventListener('click', openSettingsModal);
  elements.selfUpdateButton.addEventListener('click', runSelfUpdate);
  elements.settingsClose.addEventListener('click', closeSettingsModal);
  elements.settingsForm.addEventListener('submit', saveSettings);
  elements.settingsModal.querySelector('.settings-modal-backdrop').addEventListener('click', closeSettingsModal);
  elements.klineModalClose.addEventListener('click', closeKlineModal);
  elements.klineModal.addEventListener('click', (event) => {
    if (event.target.classList.contains('kline-modal-backdrop')) {
      closeKlineModal();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !elements.klineModal.classList.contains('hidden')) {
      closeKlineModal();
    }
  });
  elements.latestOutput.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-stock-code]');
    if (!trigger) return;
    openKlineModal(trigger.dataset.stockCode, trigger.dataset.stockName || '');
  });
  elements.dateInput.addEventListener('change', async (event) => {
    const nextDate = fromInputDate(event.target.value);
    if (!state.dates.includes(nextDate)) {
      event.target.value = state.selectedDate ? toInputDate(state.selectedDate) : '';
      setStatus('日期無效', 'failed');
      renderPlainOutput('主人，這天不是可用交易日。請從 2026/2 開始的交易日中選擇。', 'error-output');
      return;
    }
    state.selectedDate = nextDate;
    localStorage.setItem('stock-control-date', state.selectedDate);
    resetSerenityPanel();
    await loadCurrentResult();
  });

  await selectFunction(state.selectedKey);
}

init();
