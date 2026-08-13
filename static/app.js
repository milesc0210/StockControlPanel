const state = {
  functions: [],
  dates: [],
  intradayDate: '',
  selectedDate: localStorage.getItem('stock-control-date') || '',
  selectedKey: localStorage.getItem('stock-control-selected') || 'limit_up_red_arrow',
  selectedFunction: null,
  currentRun: null,
  currentKlineCode: '',
  currentKlinePayload: null,
  currentKlineSymbol: '',
  currentKlineMode: 'signal-day',
  fearGreed: null,
  backtestResult: null,
  backtestPresets: [],
  serenityResult: null,
  serenityProgressTimer: null,
  serenitySelectedCodes: new Set(),
  serenitySelectionKey: '',
  serenitySelectionInitialized: false,
  serenityAnalyzedCodes: new Set(),
  marketState: { market_open: false, now: '', timezone: 'Asia/Taipei' },
  selfUpdateProgressTimer: null,
  updateStatusChecked: false,
};

const CUSTOM_SECTOR_FUNCTION_KEY = 'custom_stock_sectors';
const CUSTOM_SECTOR_CATEGORY = '自訂功能';
const CHIP_DASHBOARD_FUNCTION_KEY = 'chip_dashboard';
const LIGHTWEIGHT_CHARTS_SCRIPT = 'https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js';
const LIGHTWEIGHT_CHARTS_INTEGRITY = 'sha384-q1KYLSKHgBnW5tWYGGR8+6YV4/iPy31dILoF2I1OD7XiVUvHEp/TaxIQVmB0j3R2';
const KLINE_CHART_LOOKBACK_DAYS = 1000;
let lightweightChartsPromise = null;
let activeKlineChart = null;
let activeKlineResizeObserver = null;
let klineRequestSerial = 0;
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
  klineSignalDayButton: document.getElementById('kline-signal-day-button'),
  klineTradingViewButton: document.getElementById('kline-tradingview-button'),
  backtestPanel: document.getElementById('backtest-panel'),
  backtestStartDate: document.getElementById('backtest-start-date'),
  backtestEndDate: document.getElementById('backtest-end-date'),
  backtestTp: document.getElementById('backtest-tp'),
  backtestSl: document.getElementById('backtest-sl'),
  backtestEntryMax: document.getElementById('backtest-entry-max'),
  backtestEntryMin: document.getElementById('backtest-entry-min'),
  backtestTopN: document.getElementById('backtest-top-n'),
  backtestTotalCapital: document.getElementById('backtest-total-capital'),
  backtestMaxHoldDays: document.getElementById('backtest-max-hold-days'),
  backtestPresetSelect: document.getElementById('backtest-preset-select'),
  backtestPresetDescription: document.getElementById('backtest-preset-description'),
  backtestPresetApplyButton: document.getElementById('backtest-preset-apply-button'),
  backtestPresetSaveButton: document.getElementById('backtest-preset-save-button'),
  backtestPresetDeleteButton: document.getElementById('backtest-preset-delete-button'),
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

function isCustomSectorFunction(functionKey = state.selectedKey) {
  return functionKey === CUSTOM_SECTOR_FUNCTION_KEY;
}

function isChipDashboardFunction(functionKey = state.selectedKey) {
  return functionKey === CHIP_DASHBOARD_FUNCTION_KEY;
}

function isIntradayFunction(functionKey = state.selectedKey) {
  return [
    'new_high_black_volume_contraction',
    'low_base_turnaround',
    'pre_breakout_conservative',
    'pre_breakout_standard',
    'ma_bullish_turning_point',
    'limit_up_red_arrow',
  ].includes(functionKey);
}

function isDirectCurrentIntradayFunction(functionKey = state.selectedKey) {
  return [
    'new_high_black_volume_contraction',
    'pre_breakout_standard',
  ].includes(functionKey);
}

function isIntradayAvailable() {
  return isIntradayFunction() && Boolean(state.selectedDate) && Boolean(state.marketState?.market_open);
}

function isCurrentIntradaySelection() {
  return isDirectCurrentIntradayFunction()
    && Boolean(state.intradayDate)
    && state.selectedDate === state.intradayDate
    && Boolean(state.marketState?.market_open);
}

function isSelectableDate(date) {
  return state.dates.includes(date)
    || (isDirectCurrentIntradayFunction() && date === state.intradayDate);
}

function getInstitutionalMap() {
  return state.currentRun?.institutional?.payload?.stocks || {};
}

function getIntradayMap() {
  return state.currentRun?.intraday?.payload?.quotes || {};
}

function getCurrentSerenityStocks() {
  if (!state.currentRun || state.currentRun.status !== 'success') return [];
  const intradayPayload = state.currentRun.intraday?.payload;
  const intradayQuotes = intradayPayload?.quotes || {};
  if (intradayPayload && Object.keys(intradayQuotes).length) {
    const liveQuotes = Object.values(intradayQuotes).filter((quote) => (
      state.currentRun.current_intraday ? quote?.matched === true : Boolean(quote)
    ));
    return liveQuotes.slice(0, 30).map((quote) => ({
      code: quote.code || '',
      name: quote.name || '',
      market: quote.market || '',
      theme: quote.theme || '',
      grade: quote.grade || '',
      rank_score: quote.rank_score || '',
      close: quote.last_price ?? '',
      volume: quote.trade_volume ?? '',
    })).filter((stock) => stock.code);
  }
  const text = state.currentRun.output_text || '';
  let parsed = parseNewHighBlackOutput(text);
  let stocks = parsed?.stocks || [];

  if (!stocks.length) {
    parsed = parseLowBaseOutput(text);
    stocks = parsed?.stocks || [];
  }

  if (!stocks.length) {
    parsed = parsePreBreakoutOutput(text);
    stocks = parsed?.stocks || [];
  }

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
    theme: stock.themeName || stock.theme || '',
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
  state.serenityAnalyzedCodes = new Set();
  state.serenitySelectedCodes = new Set();
  state.serenitySelectionKey = '';
  state.serenitySelectionInitialized = false;
  elements.serenityMeta.innerHTML = '';
  elements.serenityOutput.className = 'serenity-output empty-block';
  elements.serenityOutput.textContent = message;
  setSerenityStatus('待命', 'neutral');
}

function renderSerenityResult(payload) {
  state.serenityResult = payload;
  state.serenityAnalyzedCodes = new Set((payload.stock_codes || []).map(String));
  elements.serenityPanel.hidden = false;
  elements.serenityMeta.innerHTML = '';
  const metaItems = [
    ['選股功能', payload.function_name],
    ['交易日', formatYmd(payload.result_date)],
    ['候選股', `${payload.stock_count} 檔`],
    ['分析時間', compactTimestamp(payload.generated_at)],
    ['耗時', formatDuration(Number(payload.duration_seconds || 0))],
    ['資料來源', payload.from_cache ? 'DB 快取' : 'Hermes 即時分析'],
  ];
  if (!payload.from_cache && payload.research_mode) {
    metaItems.push(['研究模式', payload.research_mode]);
  }
  if (payload.from_cache && payload.cached_at) {
    metaItems.push(['快取時間', compactTimestamp(payload.cached_at)]);
  }
  for (const [label, value] of metaItems) {
    const div = document.createElement('div');
    div.className = 'meta-item';
    div.textContent = `${label}：${value}`;
    elements.serenityMeta.appendChild(div);
  }
  elements.serenityOutput.className = 'serenity-output';
  elements.serenityOutput.innerHTML = `<pre>${escapeHtml(payload.analysis || '(無分析內容)')}</pre>`;
  setSerenityStatus(payload.from_cache ? '已載入快取' : '分析完成', 'success');
}

async function loadSerenityCache() {
  if (!state.selectedFunction?.executable || !state.selectedDate || isFearGreedFunction()) return false;
  const functionKey = state.selectedKey;
  const resultDate = state.selectedDate;
  const query = new URLSearchParams({ result_date: resultDate });
  try {
    const response = await fetch(`/api/serenity/${encodeURIComponent(functionKey)}?${query.toString()}`);
    const payload = await response.json();
    if (functionKey !== state.selectedKey || resultDate !== state.selectedDate) return false;
    if (response.status === 404 && payload.cached === false) {
      resetSerenityPanel();
      renderActionButtons();
      return false;
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || '讀取 Serenity 快取失敗');
    }
    renderSerenityResult(payload);
    renderActionButtons();
    return true;
  } catch (error) {
    if (functionKey === state.selectedKey && resultDate === state.selectedDate) {
      resetSerenityPanel(`讀取 Serenity 快取失敗：${String(error.message || error)}`);
      setSerenityStatus('讀取失敗', 'failed');
    }
    return false;
  }
}

function renderActionButtons() {
  const isFearGreed = isFearGreedFunction();
  const isCustomSector = isCustomSectorFunction();
  const isChipDashboard = isChipDashboardFunction();
  const showSerenity = !isFearGreed && !isCustomSector && !isChipDashboard && Boolean(state.selectedFunction?.executable);
  const serenityStocks = getCurrentSerenityStocks();
  const selectedSerenityStocks = showSerenity ? getSelectedSerenityStocks() : [];
  const showInstitutional = !isFearGreed && isPreBreakoutFunction() && Boolean(state.selectedDate);
  const showIntraday = !isFearGreed && isIntradayFunction() && Boolean(state.selectedDate);
  const showBacktest = !isFearGreed && isBacktestFunction();
  elements.dateControlWrap.hidden = isFearGreed || isChipDashboard;
  elements.runButton.hidden = isCustomSector || isChipDashboard || !state.selectedFunction?.executable;
  elements.refreshFutureButton.hidden = isFearGreed || isCustomSector || isChipDashboard || !state.selectedFunction?.executable;
  elements.serenityButton.hidden = !showSerenity;
  elements.serenityPanel.hidden = !showSerenity;
  elements.serenityButton.textContent = selectedSerenityStocks.length
    ? `Serenity 深度分析（${selectedSerenityStocks.length} 檔）`
    : 'Serenity 深度分析';
  elements.serenityButton.disabled = !selectedSerenityStocks.length;
  elements.serenityButton.title = selectedSerenityStocks.length
    ? `分析已勾選的 ${selectedSerenityStocks.length} 檔股票（共 ${serenityStocks.length} 檔）`
    : serenityStocks.length ? '請至少勾選 1 檔股票再開始分析' : '請先執行選股，產生候選股票後才能分析';
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

function formatSignedPercent(value) {
  return formatChangePercent(value);
}

function formatPercentagePoints(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const sign = number > 0 ? '+' : '';
  return `${sign}${number.toFixed(2)} 個百分點`;
}

function toneClassFromNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '';
  if (number > 0) return 'up-text';
  if (number < 0) return 'down-text';
  return '';
}

function buildCodeButton(stock) {
  return `<button class="stock-code-button" data-stock-code="${escapeHtml(stock.code)}" data-stock-name="${escapeHtml(stock.name)}" data-stock-market="${escapeHtml(stock.market || '')}">${escapeHtml(stock.code)}</button>`;
}

function buildInlineKlineSlot(stock) {
  return `<td class="td-mini-kline"><div class="mini-kline-slot" data-inline-kline="${escapeHtml(stock.code)}">載入中...</div></td>`;
}

function serenitySelectionKey() {
  return `${state.selectedKey}::${state.selectedDate || ''}`;
}

function syncSerenitySelection(stocks) {
  const codes = [...new Set((stocks || []).map((stock) => String(stock.code || '').trim()).filter(Boolean))];
  if (!codes.length) return codes;
  const key = serenitySelectionKey();
  if (!state.serenitySelectionInitialized || state.serenitySelectionKey !== key) {
    state.serenitySelectedCodes = new Set();
    state.serenitySelectionKey = key;
    state.serenitySelectionInitialized = true;
  } else {
    const available = new Set(codes);
    state.serenitySelectedCodes = new Set(
      [...state.serenitySelectedCodes].filter((code) => available.has(code)),
    );
  }
  return codes;
}

function getSelectedSerenityStocks() {
  const stocks = getCurrentSerenityStocks();
  syncSerenitySelection(stocks);
  return stocks.filter((stock) => state.serenitySelectedCodes.has(String(stock.code || '').trim()));
}

function sameStockCodeSet(left, right) {
  const a = [...new Set((left || []).map(String))].sort();
  const b = [...new Set(right || [])].sort();
  return a.length === b.length && a.every((code, index) => code === b[index]);
}

function updateSerenitySelectionUI() {
  const stocks = getCurrentSerenityStocks();
  const selected = getSelectedSerenityStocks();
  const selectedCount = selected.length;
  elements.serenityButton.textContent = selectedCount
    ? `Serenity 深度分析（${selectedCount} 檔）`
    : 'Serenity 深度分析';
  elements.serenityButton.disabled = !selectedCount;
  elements.serenityButton.title = selectedCount
    ? `分析已勾選的 ${selectedCount} 檔股票（共 ${stocks.length} 檔）`
    : '請至少勾選 1 檔股票再開始分析';

  const checkboxes = [...elements.latestOutput.querySelectorAll('input[data-serenity-stock]')];
  for (const checkbox of checkboxes) {
    checkbox.checked = state.serenitySelectedCodes.has(checkbox.dataset.serenityStock);
  }
  const selectAll = elements.latestOutput.querySelector('input[data-serenity-select-all]');
  if (selectAll) {
    selectAll.checked = Boolean(stocks.length) && selectedCount === stocks.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < stocks.length;
  }
}

function installSerenitySelectionControls(stocks) {
  syncSerenitySelection(stocks);
  const table = elements.latestOutput.querySelector('table.stock-table');
  if (!table) {
    updateSerenitySelectionUI();
    return;
  }

  const headerRow = table.querySelector('thead tr');
  if (headerRow) {
    const headerCell = document.createElement('th');
    headerCell.className = 'th-serenity-select';
    const selectAll = document.createElement('input');
    selectAll.type = 'checkbox';
    selectAll.dataset.serenitySelectAll = 'true';
    selectAll.setAttribute('aria-label', '全選或取消全選 Serenity 深度分析股票');
    selectAll.title = '全選或取消全選';
    headerCell.appendChild(selectAll);
    headerRow.insertBefore(headerCell, headerRow.firstChild);
    selectAll.addEventListener('change', () => {
      const codes = syncSerenitySelection(stocks);
      state.serenitySelectedCodes = selectAll.checked ? new Set(codes) : new Set();
      updateSerenitySelectionUI();
    });
  }

  const stockRows = [...table.querySelectorAll('tbody tr')].filter(
    (row) => !row.classList.contains('group-divider-row'),
  );
  stockRows.forEach((row, index) => {
    const stock = stocks[index];
    if (!stock?.code) return;
    const cell = document.createElement('td');
    cell.className = 'td-serenity-select';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.dataset.serenityStock = String(stock.code);
    checkbox.setAttribute('aria-label', `選擇 ${stock.code} ${stock.name || ''} 進行 Serenity 深度分析`);
    checkbox.checked = state.serenitySelectedCodes.has(String(stock.code));
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        state.serenitySelectedCodes.add(String(stock.code));
      } else {
        state.serenitySelectedCodes.delete(String(stock.code));
      }
      updateSerenitySelectionUI();
    });
    cell.appendChild(checkbox);
    row.insertBefore(cell, row.firstChild);
  });

  for (const row of table.querySelectorAll('tbody tr.group-divider-row')) {
    const firstCell = row.firstElementChild;
    if (firstCell) firstCell.colSpan = Number(firstCell.colSpan || 1) + 1;
  }
  updateSerenitySelectionUI();
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
  const klineEndDate = state.currentRun?.intraday?.payload?.source_result_date || state.selectedDate;
  if (!codes.length || !klineEndDate) return;

  try {
    const response = await fetch('/api/kline_batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        codes,
        end_date: klineEndDate,
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

function clearLightweightKlineChart() {
  if (activeKlineResizeObserver) {
    activeKlineResizeObserver.disconnect();
    activeKlineResizeObserver = null;
  }
  if (activeKlineChart) {
    activeKlineChart.remove();
    activeKlineChart = null;
  }
}

function closeKlineModal() {
  klineRequestSerial += 1;
  clearLightweightKlineChart();
  elements.klineModal.classList.add('hidden');
  elements.klineModal.setAttribute('aria-hidden', 'true');
  elements.klineModalBody.replaceChildren();
  state.currentKlineCode = '';
  state.currentKlinePayload = null;
  state.currentKlineSymbol = '';
  state.currentKlineMode = 'signal-day';
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

function openKlineModalShell(code, name, market) {
  state.currentKlineCode = code;
  state.currentKlinePayload = null;
  state.currentKlineSymbol = '';
  state.currentKlineMode = 'signal-day';
  elements.klineModal.classList.remove('hidden');
  elements.klineModal.setAttribute('aria-hidden', 'false');
  elements.klineModalTitle.textContent = `${code} ${name}｜訊號日 K 線`;
  elements.klineModalMeta.textContent = `${market || '台股'} ｜ 本機歷史資料 ｜ 連線中...`;
  elements.klineModalBody.innerHTML = '<div class="kline-loading">正在載入 TradingView K 線圖...</div>';
  elements.klineSignalDayButton.disabled = true;
  elements.klineTradingViewButton.disabled = true;
  setKlineModeButtonState('signal-day');
}

function linePath(points) {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ');
}

function setKlineModeButtonState(mode) {
  state.currentKlineMode = mode;
  elements.klineSignalDayButton.classList.toggle('active', mode === 'signal-day');
}

function openTradingViewFullChart() {
  const symbol = state.currentKlineSymbol;
  if (!symbol) {
    elements.klineModalMeta.textContent = 'TradingView 完整圖表目前缺少股票市場資訊。';
    return;
  }
  const url = buildTradingViewSymbolUrl(symbol);
  window.open(url, '_blank', 'noopener,noreferrer');
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

function renderLocalKlineFallback(payload) {
  const fallbackCount = Math.min(60, (payload.rows || []).length);
  const sliceStart = Math.max(0, (payload.rows || []).length - fallbackCount);
  const fallbackPayload = {
    ...payload,
    rows: (payload.rows || []).slice(sliceStart),
    ma5: (payload.ma5 || []).slice(sliceStart),
    ma10: (payload.ma10 || []).slice(sliceStart),
    ma20: (payload.ma20 || []).slice(sliceStart),
    start_date: (payload.rows || [])[sliceStart]?.date || payload.start_date,
    count: fallbackCount,
  };
  renderKlineModal(fallbackPayload);
  elements.klineModalMeta.textContent += ' ｜ TradingView 元件無法載入，已改用本機 K 線圖';
}

async function renderSignalDayKline(requestId = klineRequestSerial) {
  if (!state.currentKlinePayload || !state.currentKlineSymbol) return;
  setKlineModeButtonState('signal-day');
  try {
    const lightweightCharts = await loadLightweightCharts();
    if (requestId !== klineRequestSerial || state.currentKlineCode !== state.currentKlinePayload.code) return;
    renderTradingViewKline(state.currentKlinePayload, lightweightCharts, state.currentKlineSymbol);
  } catch (chartError) {
    if (requestId !== klineRequestSerial) return;
    renderLocalKlineFallback(state.currentKlinePayload);
  }
}

function loadLightweightCharts() {
  const hasV5Series = (library) => Boolean(
    library?.createChart
    && library?.CandlestickSeries
    && library?.HistogramSeries
  );
  if (hasV5Series(window.LightweightCharts)) return Promise.resolve(window.LightweightCharts);
  if (lightweightChartsPromise) return lightweightChartsPromise;

  lightweightChartsPromise = new Promise((resolve, reject) => {
    const existing = [...document.scripts].find((item) => item.src === LIGHTWEIGHT_CHARTS_SCRIPT);
    const script = existing || document.createElement('script');
    let timeoutId = null;
    const rejectAndReset = (error) => {
      if (timeoutId) window.clearTimeout(timeoutId);
      lightweightChartsPromise = null;
      script.remove();
      reject(error);
    };
    const finish = () => {
      if (hasV5Series(window.LightweightCharts)) {
        if (timeoutId) window.clearTimeout(timeoutId);
        resolve(window.LightweightCharts);
      } else {
        rejectAndReset(new Error('TradingView Lightweight Charts v5.2 載入後找不到系列定義。'));
      }
    };

    script.addEventListener('load', finish, { once: true });
    script.addEventListener('error', () => rejectAndReset(new Error('TradingView Lightweight Charts 載入失敗。')), { once: true });
    timeoutId = window.setTimeout(
      () => rejectAndReset(new Error('TradingView Lightweight Charts 載入逾時。')),
      8000,
    );
    if (!existing) {
      script.src = LIGHTWEIGHT_CHARTS_SCRIPT;
      script.integrity = LIGHTWEIGHT_CHARTS_INTEGRITY;
      script.crossOrigin = 'anonymous';
      script.async = true;
      document.head.appendChild(script);
    } else if (window.LightweightCharts) {
      finish();
    }
  });
  return lightweightChartsPromise;
}

function buildTradingViewSymbol(code, market) {
  const normalizedCode = String(code || '').trim();
  const normalizedMarket = String(market || '').trim().toUpperCase();
  if (!/^\d{4,6}$/.test(normalizedCode)) return '';
  const exchangePrefixes = { TWSE: 'TWSE:', TPEX: 'TPEX:' };
  const prefix = exchangePrefixes[normalizedMarket];
  return prefix ? `${prefix}${normalizedCode}` : '';
}

function formatKlineTime(value) {
  const text = String(value || '').trim();
  if (/^\d{8}$/.test(text)) return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  return text.replaceAll('/', '-');
}

function buildTradingViewSymbolUrl(symbol) {
  const [exchange, code] = String(symbol || '').split(':');
  if (!exchange || !code) return 'https://www.tradingview.com/';
  return `https://www.tradingview.com/symbols/${encodeURIComponent(exchange)}-${encodeURIComponent(code)}/`;
}

function buildKlineLineData(rowEntries, values) {
  if (!Array.isArray(values)) return [];
  return rowEntries.map(({ row, index }) => {
    const rawValue = values[index];
    if (rawValue === null || rawValue === undefined || rawValue === '') return null;
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return null;
    return { time: formatKlineTime(row.date), value };
  }).filter(Boolean);
}

function renderTradingViewKline(payload, lightweightCharts, symbol) {
  const rowEntries = (payload.rows || [])
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => row && [row.open, row.high, row.low, row.close, row.volume].every((value) => Number.isFinite(Number(value))));
  const rows = rowEntries.map(({ row }) => row);
  if (!rows.length) {
    elements.klineModalBody.innerHTML = '<div class="empty-block">目前沒有可顯示的長期 K 線資料。</div>';
    return;
  }

  clearLightweightKlineChart();
  const latest = rows[rows.length - 1];
  const chartWrap = document.createElement('div');
  chartWrap.className = 'tradingview-chart-wrap';
  const reading = document.createElement('div');
  reading.className = 'tradingview-kline-reading';
  reading.textContent = `最新收盤 ${formatPrice(latest.close)} ｜ 開 ${formatPrice(latest.open)}　高 ${formatPrice(latest.high)}　低 ${formatPrice(latest.low)}　量 ${formatVolume(latest.volume)}`;
  const legend = document.createElement('div');
  legend.className = 'tradingview-kline-legend';
  legend.innerHTML = `
    <span><i class="tradingview-kline-legend-line ma5"></i>MA5</span>
    <span><i class="tradingview-kline-legend-line ma10"></i>MA10</span>
    <span><i class="tradingview-kline-legend-line ma20"></i>MA20</span>`;

  const chartMount = document.createElement('div');
  chartMount.className = 'tradingview-chart-mount';
  const attribution = document.createElement('div');
  attribution.className = 'tradingview-widget-copyright';
  const tradingViewLink = buildTradingViewSymbolUrl(symbol);
  attribution.innerHTML = `<a href="https://tradingview.github.io/lightweight-charts/" target="_blank" rel="noopener nofollow"><span class="blue-text">TradingView Lightweight Charts</span></a> · <a href="${tradingViewLink}" target="_blank" rel="noopener nofollow">在 TradingView 查看完整圖表</a>`;
  chartWrap.append(reading, legend, chartMount, attribution);
  elements.klineModalBody.replaceChildren(chartWrap);

  const chart = lightweightCharts.createChart(chartMount, {
    width: chartMount.clientWidth || 900,
    height: chartMount.clientHeight || 520,
    layout: {
      background: { type: 'solid', color: '#ffffff' },
      textColor: '#64748b',
    },
    grid: {
      vertLines: { color: '#eef2f7' },
      horzLines: { color: '#eef2f7' },
    },
    rightPriceScale: { borderColor: '#dfe7f7' },
    timeScale: {
      borderColor: '#dfe7f7',
      timeVisible: false,
      secondsVisible: false,
      rightOffset: 4,
    },
    crosshair: {
      mode: lightweightCharts.CrosshairMode?.Normal ?? 0,
    },
    handleScale: {
      mouseWheel: true,
      pinch: true,
      axisPressedMouseMove: true,
    },
    handleScroll: {
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: true,
    },
  });

  const candleSeries = chart.addSeries(lightweightCharts.CandlestickSeries, {
    upColor: '#c83f49',
    downColor: '#1e8e5a',
    borderUpColor: '#c83f49',
    borderDownColor: '#1e8e5a',
    wickUpColor: '#c83f49',
    wickDownColor: '#1e8e5a',
  });
  candleSeries.setData(rows.map((row) => ({
    time: formatKlineTime(row.date),
    open: Number(row.open),
    high: Number(row.high),
    low: Number(row.low),
    close: Number(row.close),
  })));

  const movingAverageSeries = [
    { label: 'MA5', color: '#1f77b4', values: payload.ma5 },
    { label: 'MA10', color: '#ff7f0e', values: payload.ma10 },
    { label: 'MA20', color: '#222222', values: payload.ma20 },
  ];
  for (const movingAverage of movingAverageSeries) {
    const series = chart.addSeries(lightweightCharts.LineSeries, {
      color: movingAverage.color,
      lineWidth: 2,
      title: movingAverage.label,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(buildKlineLineData(rowEntries, movingAverage.values));
  }

  const volumeSeries = chart.addSeries(lightweightCharts.HistogramSeries, {
    color: '#94a3b8',
    priceFormat: { type: 'volume' },
    priceScaleId: '',
  });
  volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  volumeSeries.setData(rows.map((row) => ({
    time: formatKlineTime(row.date),
    value: Number(row.volume),
    color: Number(row.close) >= Number(row.open) ? 'rgba(200, 63, 73, 0.65)' : 'rgba(30, 142, 90, 0.65)',
  })));

  activeKlineChart = chart;
  const resize = () => {
    if (!activeKlineChart || !chartMount.isConnected) return;
    chart.applyOptions({ width: chartMount.clientWidth || 900, height: chartMount.clientHeight || 520 });
  };
  if (window.ResizeObserver) {
    activeKlineResizeObserver = new ResizeObserver(resize);
    activeKlineResizeObserver.observe(chartMount);
  }
  chart.timeScale().fitContent();
  window.requestAnimationFrame(resize);

  const selectedDateText = state.selectedDate ? ` ｜ 選股日期 ${formatYmd(state.selectedDate)}` : '';
  setKlineModeButtonState('signal-day');
  elements.klineModalTitle.textContent = `${payload.code} ${payload.name}｜訊號日 K 線`;
  elements.klineModalMeta.textContent = `${payload.market} ｜ 本機歷史資料 ｜ ${formatYmd(payload.start_date)} ～ ${formatYmd(payload.end_date)} ｜ 共 ${payload.count} 根${selectedDateText}`;
}

async function openKlineModal(code, name, market) {
  if (!code) return;
  const requestId = ++klineRequestSerial;
  const normalizedMarket = market || '';
  openKlineModalShell(code, name || '', normalizedMarket);

  try {
    const query = new URLSearchParams({
      end_date: state.selectedDate || '',
      lookback_days: String(KLINE_CHART_LOOKBACK_DAYS),
    });
    const response = await fetch(`/api/kline/${encodeURIComponent(code)}?${query.toString()}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || '讀取長期 K 線資料失敗');
    }
    if (requestId !== klineRequestSerial || state.currentKlineCode !== code) return;
    const symbol = buildTradingViewSymbol(code, normalizedMarket || payload.market);
    if (!symbol) {
      throw new Error('找不到股票的 TWSE / TPEX 市場資訊。');
    }
    state.currentKlinePayload = payload;
    state.currentKlineSymbol = symbol;
    elements.klineSignalDayButton.disabled = false;
    elements.klineTradingViewButton.disabled = false;
    await renderSignalDayKline(requestId);
  } catch (error) {
    if (requestId !== klineRequestSerial || state.currentKlineCode !== code) return;
    elements.klineModalBody.innerHTML = `<div class="empty-block">${escapeHtml(String(error.message || error))}</div>`;
    elements.klineModalMeta.textContent = `TradingView K 線資料載入失敗 ｜ ${String(error.message || error)}`;
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
  const latest = isDirectCurrentIntradayFunction() && state.intradayDate
    ? state.intradayDate
    : (hasDates ? state.dates[0] : '');

  elements.dateInput.value = state.selectedDate ? toInputDate(state.selectedDate) : '';
  elements.dateInput.min = earliest ? toInputDate(earliest) : '';
  elements.dateInput.max = latest ? toInputDate(latest) : '';
  elements.dateInput.disabled = !hasDates;

  if (hasDates) {
    elements.dateNote.textContent = isDirectCurrentIntradayFunction() && state.intradayDate
      ? `可選擇的日期：${toInputDate(earliest).replaceAll('-', '/')} 起；目前盤中日期 ${toInputDate(state.intradayDate).replaceAll('-', '/')} 可直接選股`
      : `可選擇的日期：${toInputDate(earliest).replaceAll('-', '/')} 起的交易日`;
  } else {
    elements.dateNote.textContent = '目前沒有可選日期';
  }
}


function parseNewHighBlackOutput(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.startsWith('策略：創高黑量縮'))) return null;

  const summary = {};
  const stocks = [];
  for (const line of lines) {
    if (line.startsWith('比較區間：')) summary.range = line.replace('比較區間：', '').trim();
    if (line.startsWith('參考前日：')) summary.referenceDate = line.replace('參考前日：', '').trim();
    if (line.startsWith('訊號日期：')) summary.signalDate = line.replace('訊號日期：', '').trim();
    if (line.startsWith('入選數量：')) summary.count = line.replace('入選數量：', '').trim();
    if (line.startsWith('盤中觀察數量：')) summary.watchCount = line.replace('盤中觀察數量：', '').trim();

    const match = line.match(/^RESULT\s+(TWSE|TPEX)\s+([0-9A-Z]+)\s+(.+?)\s+\|\s+SETUP\s+(\d{8})\s+O=([\d.]+)\s+H=([\d.]+)\s+L=([\d.]+)\s+C=([\d.]+)\s+V=([\d.]+)張\s+\|\s+SIGNAL\s+(\d{8})\s+O=([\d.]+)\s+H=([\d.]+)\s+L=([\d.]+)\s+C=([\d.]+)\s+V=([\d.]+)張\s+MA5=([\d.]+)\s+分數=([\d.]+)\s+\|\s+後5日=(.+)$/);
    if (!match) continue;
    const futureText = match[18].trim();
    const futureDays = futureText === '(無後續資料)'
      ? []
      : futureText.split(/,\s*/).map((entry) => {
          const future = entry.match(/^(\d{8}):([\d.]+)\/([+-]\d+\.\d+%)\/([+-]\d+\.\d+%)$/);
          return future ? {
            date: future[1], close: future[2], pctFromSignal: future[3], pctFromPrev: future[4],
          } : null;
        }).filter(Boolean);
    stocks.push({
      market: match[1], code: match[2], name: match[3],
      setupDate: match[4], setupOpen: match[5], setupHigh: match[6], setupLow: match[7],
      setupClose: match[8], setupVolume: match[9], signalDate: match[10], signalOpen: match[11],
      signalHigh: match[12], signalLow: match[13], close: match[14], volume: match[15],
      ma5: match[16], rankScore: match[17], futureDays,
    });
  }
  return { type: 'new_high_black', summary, stocks };
}

function parseLimitUpOutput(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.includes('策略：前一交易日漲停') || line.includes('策略：指定日期漲停') || line.includes('策略：創高黑量縮'))) return null;

  const summary = {};
  const stocks = [];
  for (const line of lines) {
    if (line.startsWith('比較區間：')) summary.range = line.replace('比較區間：', '').trim();
    if (line.startsWith('參考前日：')) summary.referenceDate = line.replace('參考前日：', '').trim();
    if (line.startsWith('入選數量：')) summary.count = line.replace('入選數量：', '').trim();
    const match = line.match(/^(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+.+?C=([\d.]+)\s+V=([\d.]+張)(?:\s+\|\s+上影=([\d.]+)\s+實體=([\d.]+)\s+比=([\d.-]+))?(?:\s+MA4合計=[\d.]+)?(?:\s+分數=([\d.]+))?(?:\s+\|\s+後5日=(.+))?$/);
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

function parseLowBaseOutput(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (!lines.some((line) => line.includes('LOW-BASE-TURNAROUND'))) return null;

  const summary = {};
  const stocks = [];
  for (const line of lines) {
    if (line.startsWith('交易日：')) summary.date = line.replace('交易日：', '').trim();
    if (line.startsWith('市場60日中位數：')) summary.marketMedian = line.replace('市場60日中位數：', '').trim();
    if (line.startsWith('評估母體：')) summary.universe = line.replace('評估母體：', '').trim();
    if (line.startsWith('入選數量：')) summary.count = line.replace('入選數量：', '').trim();

    const match = line.match(/^([AB])\s+(TWSE|TPEX)\s+(\d+)\s+(.+?)\s+\|\s+族群=(\S+)\s+C=([\d.]+)\s+V=(\d+)張\s+60日=([+-]?[\d.]+)%\s+市場百分位=([\d.]+)\s+族群差=([+-]?[\d.]+)%\s+5日轉強=([+-]?[\d.]+)%\s+量比=([\d.]+)\s+分數=([\d.]+)\s+\|\s+後5日=(.+)$/);
    if (!match) continue;
    const futureRaw = match[14].trim();
    const futureDays = futureRaw === '(無後續資料)'
      ? []
      : futureRaw.split(/\s*,\s*/).map((chunk) => {
          const parts = chunk.match(/^(\d{8}):([\d.]+)\/([+-]?[\d.]+%)\/([+-]?[\d.]+%)$/);
          if (!parts) return null;
          return { date: parts[1], close: parts[2], pctFromSignal: parts[3], pctFromPrev: parts[4] };
        }).filter(Boolean);
    stocks.push({
      grade: match[1],
      market: match[2],
      code: match[3],
      name: match[4],
      theme: match[5],
      close: match[6],
      volume: match[7],
      return60d: match[8],
      marketPercentile: match[9],
      sectorRelative: match[10],
      rebound5d: match[11],
      volumeRatio: match[12],
      rankScore: match[13],
      futureDays,
    });
  }
  return { type: 'low_base', summary, stocks };
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
  return { type: 'pre_breakout', summary, stocks, sector: parseSectorQuickOutput(text) };
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
  if (!lines.some((line) => line.includes('策略：0121 快速族群分析') || line.includes('策略：今日漲停 快速族群分析') || line.includes('策略：標準選股 快速族群分析'))) return null;

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

function csvCell(value) {
  const text = value === null || value === undefined ? '' : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadBacktestCsv() {
  const payload = state.backtestResult;
  const trades = payload?.trades || [];
  if (!trades.length) {
    setBacktestStatus('沒有可匯出的交易', 'failed');
    return;
  }
  const params = payload.params || {};
  const headers = ['策略', '訊號日期', '市場', '股票代號', '股票名稱', '買進日期', '買進時間', '買進價格', '買進股數', '整張股數', '零股股數', '買進成本', '賣出日期', '賣出時間', '賣出價格', '賣出原因', '持有天數', '報酬率%', '損益', '每檔分配預算', '停利%', '停損%', '最多持有天數'];
  const rows = trades.map((trade) => [
    payload.function_name, formatYmd(trade.signal_date), trade.market, trade.code, trade.name,
    formatYmd(trade.entry_date), '收盤', trade.entry_close, trade.shares, trade.board_lots * 1000, trade.odd_lot_shares, trade.cost,
    formatYmd(trade.exit_date), trade.exit_reason === 'time_exit' ? '收盤' : '日線觸發（無分時資料）', trade.exit_price, trade.exit_reason,
    trade.days_held, trade.ret_pct, trade.pnl, trade.budget, params.take_profit_pct, params.stop_loss_pct, params.max_hold_days,
  ]);
  const csv = `\uFEFF${[headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n')}`;
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `回測明細_${payload.function_key}_${params.start_date}_${params.end_date}.csv`;
  link.click();
  URL.revokeObjectURL(url);
  setBacktestStatus('CSV 已下載', 'success');
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
    <div class="backtest-export-actions"><button id="backtest-csv-download-button" class="text-button">下載回測明細 CSV</button></div>
    <div class="backtest-summary-grid">
      <div class="backtest-summary-card"><span>累計損益</span><strong class="${Number(summary.net_pnl_ntd) >= 0 ? 'up-text' : 'down-text'}">${formatMoney(summary.net_pnl_ntd)}</strong></div>
      <div class="backtest-summary-card"><span>報酬率</span><strong class="${Number(summary.aggregate_roi_pct) >= 0 ? 'up-text' : 'down-text'}">${formatSignedPercent(summary.aggregate_roi_pct)}</strong></div>
      <div class="backtest-summary-card"><span>勝率</span><strong>${formatSignedPercent(summary.win_rate_pct).replace('+', '')}</strong></div>
      <div class="backtest-summary-card"><span>最大回撤</span><strong class="down-text">${formatMoney(summary.max_drawdown_ntd)}</strong></div>
      <div class="backtest-summary-card"><span>成交筆數</span><strong>${escapeHtml(summary.trade_count)}</strong></div>
      <div class="backtest-summary-card"><span>實際總投入</span><strong>${formatMoney(summary.total_deployed_ntd)}</strong></div>
      <div class="backtest-summary-card"><span>準備資金</span><strong title="回測期間同時持有部位的最高實際投入金額">${formatMoney(summary.peak_concurrent_capital_ntd)}</strong></div>
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

  elements.backtestOutput.querySelector('#backtest-csv-download-button').addEventListener('click', downloadBacktestCsv);
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

function renderNewHighBlack(parsed) {
  const intradayMap = getIntradayMap();
  const intradaySummary = state.currentRun?.intraday?.payload;
  const currentIntradayRun = Boolean(state.currentRun?.current_intraday);
  const liveStocks = intradaySummary
    ? Object.values(intradayMap).filter((quote) => currentIntradayRun ? quote?.matched === true : quote)
    : [];
  const showingLive = Boolean(intradaySummary);
  const stocks = showingLive ? liveStocks : sortStocksByRankScore(parsed.stocks);
  const quoteDateLabel = intradaySummary?.quote_date
    ? `${formatYmd(intradaySummary.quote_date)}股價`
    : '即時價';
  const quoteVolumeLabel = intradaySummary?.quote_date
    ? `${formatYmd(intradaySummary.quote_date)}量`
    : '即時量';
  const intradayStatus = intradaySummary
    ? (currentIntradayRun
        ? `${intradaySummary.matched_count}/${intradaySummary.count} 符合｜${compactTimestamp(intradaySummary.finished_at)}`
        : `${intradaySummary.success_count}/${intradaySummary.count} 檔已更新｜${compactTimestamp(intradaySummary.finished_at)}`)
    : (state.marketState?.market_open ? `尚未查詢（觀察 ${parsed.summary.watchCount || 0} 檔）` : '盤後顯示完成交易日結果');
  const displayDate = state.currentRun?.current_intraday
    ? state.currentRun.result_date
    : parsed.summary.signalDate;
  const displayCount = state.currentRun?.current_intraday
    ? intradaySummary?.matched_count
    : parsed.summary.count;

  let html = `<div class="summary-grid">${buildSummaryChips({
    '交易日': displayDate,
    '入選數量': displayCount,
    '即時行情': intradayStatus,
  })}</div>`;

  if (!stocks.length) {
    html += `<div class="empty-block">${showingLive
      ? '目前盤中沒有符合未再創高、量縮、成交量至少 1000 張且股價不低於 MA5 的 -5% 的股票。'
      : '這個交易日沒有符合未再創高、量縮、成交量至少 1000 張且收盤不低於 MA5 的 -5% 的股票。'}</div>`;
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = html;
    return;
  }

  const maxFutureDays = showingLive ? 0 : Math.min(5, Math.max(...stocks.map((stock) => stock.futureDays.length)));
  html += '<div class="table-wrapper"><table class="stock-table"><thead><tr>';
  if (showingLive) {
    html += `<th>代號</th><th>名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">${escapeHtml(quoteDateLabel)}</th><th style="text-align:right">${escapeHtml(quoteVolumeLabel)}</th><th style="text-align:right">MA5</th><th>狀態</th>`;
  } else {
    html += '<th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th>名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">收盤</th><th style="text-align:right">成交量</th><th style="text-align:right">MA5</th>';
    if (maxFutureDays > 0) {
      const headerStock = stocks.find((stock) => stock.futureDays.length >= maxFutureDays);
      for (const day of (headerStock?.futureDays || []).slice(0, maxFutureDays)) {
        html += `<th style="text-align:center">${escapeHtml(formatYmd(day.date).slice(5))}</th>`;
      }
      html += '<th style="text-align:center">合計%</th>';
    }
    html += '<th>狀態</th>';
  }
  html += '</tr></thead><tbody>';

  for (const stock of stocks) {
    html += '<tr>';
    if (showingLive) {
      html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
      html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
      html += buildInlineKlineSlot(stock);
      const intradayTone = toneClassFromNumber(stock.change_percent);
      const intradayPriceCellClass = stock.error ? 'td-future td-empty' : `td-future td-intraday ${intradayTone}`;
      const intradayPrice = stock.error ? '—' : formatPrice(stock.last_price);
      const intradayChange = stock.error ? '' : formatChangePercent(stock.change_percent);
      html += `<td class="${intradayPriceCellClass}"><strong>${intradayPrice}</strong>${stock.error ? '' : `<span class="${intradayTone}">${escapeHtml(intradayChange)}</span>`}</td>`;
      html += `<td class="td-number">${formatVolume(stock.trade_volume)}</td>`;
      html += `<td class="td-number">${formatPrice(stock.ma5)}</td>`;
      const liveStatusClass = stock.error ? 'failed' : (stock.matched ? 'success' : 'running');
      const liveStatusText = stock.error ? '行情失敗' : (stock.matched ? '盤中符合' : '盤中未符合');
      html += `<td><span class="status-pill ${liveStatusClass}">${liveStatusText}</span></td>`;
    } else {
      html += `<td class="td-number td-score">${escapeHtml(stock.rankScore)}</td>`;
      html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
      html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
      html += buildInlineKlineSlot(stock);
      html += `<td class="td-number">${escapeHtml(stock.close)}</td>`;
      html += `<td class="td-number">${formatVolume(stock.volume)}</td>`;
      html += `<td class="td-number">${escapeHtml(stock.ma5)}</td>`;
      if (maxFutureDays > 0) {
        for (let index = 0; index < maxFutureDays; index++) {
          const day = stock.futureDays[index];
          if (!day) {
            html += '<td class="td-future td-empty">—</td>';
            continue;
          }
          const prevCls = day.pctFromPrev.startsWith('+') ? 'up-text' : day.pctFromPrev.startsWith('-') ? 'down-text' : '';
          html += `<td class="td-future"><strong>${escapeHtml(day.close)}</strong><span class="${prevCls}">${escapeHtml(day.pctFromPrev)}</span></td>`;
        }
        const lastDay = stock.futureDays[Math.min(stock.futureDays.length, maxFutureDays) - 1];
        html += lastDay
          ? `<td class="td-future td-total"><span class="${lastDay.pctFromSignal.startsWith('+') ? 'up-text' : lastDay.pctFromSignal.startsWith('-') ? 'down-text' : ''}">${escapeHtml(lastDay.pctFromSignal)}</span></td>`
          : '<td class="td-future td-empty">—</td>';
      }
      html += '<td><span class="status-pill success">收盤符合</span></td>';
    }
    html += '</tr>';
  }
  html += '</tbody></table></div>';
  elements.latestOutput.className = 'output-box rich-output';
  elements.latestOutput.innerHTML = html;
  installSerenitySelectionControls(stocks);
  hydrateInlineKlines(stocks);
}

function renderLimitUp(parsed) {
  const enrichedStocks = enrichMaBullishStocks(parsed.stocks, parsed.sector);
  const rankedStocks = parsed.sector ? enrichedStocks : sortStocksByRankScore(enrichedStocks);
  const intradayMap = getIntradayMap();
  const intradaySummary = state.currentRun?.intraday?.payload;
  const isNewHighBlack = state.selectedKey === 'new_high_black_volume_contraction';
  const stocks = isNewHighBlack && intradaySummary
    ? rankedStocks.filter((stock) => intradayMap[stock.code]?.matched === true)
    : rankedStocks;
  const showIntradayColumns = isIntradayFunction();

  if (!stocks.length) {
    const emptyIntradayStatus = showIntradayColumns
      ? (intradaySummary
          ? `${intradaySummary.matched_count}/${intradaySummary.count} 符合｜${compactTimestamp(intradaySummary.finished_at)}`
          : (state.marketState?.market_open ? '尚未查詢' : '盤後停用'))
      : '';
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = `
      <div class="summary-grid">${buildSummaryChips({
        '比較區間': parsed.summary.range,
        '入選數量': parsed.summary.count,
        '即時行情': emptyIntradayStatus,
      })}</div>
      <div class="empty-block">${isNewHighBlack && intradaySummary ? '目前盤中沒有符合「未再創高、量縮、股價不低於 MA5 的 -5%」的股票。' : '沒有可顯示的股票。'}</div>`;
    return;
  }

  const maxFutureDays = Math.max(...stocks.map((s) => s.futureDays.length));
  const extraIntradayColumns = showIntradayColumns ? 2 : 0;
  const totalColumns = (parsed.sector ? 1 : 0) + 6 + extraIntradayColumns + (maxFutureDays > 0 ? maxFutureDays + 1 : 0);
  const intradayStatus = showIntradayColumns
    ? (intradaySummary
        ? (isNewHighBlack
            ? `${intradaySummary.matched_count}/${intradaySummary.count} 符合｜${compactTimestamp(intradaySummary.finished_at)}`
            : `${intradaySummary.success_count}/${intradaySummary.count}｜${compactTimestamp(intradaySummary.finished_at)}`)
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
  html += `<th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th>名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">${isNewHighBlack ? '前日收盤' : '收盤'}</th><th style="text-align:right">${isNewHighBlack ? '前日量' : '成交量'}</th>`;
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
    if (parsed.sector && stock.themeName && stock.themeName !== currentTheme) {
      currentTheme = stock.themeName;
      const themeMeta = parsed.sector.themeRows.find((row) => row.themeName === stock.themeName);
      const themeLabel = themeMeta ? `${themeMeta.themeName}｜${themeMeta.count} 檔` : stock.themeName;
      html += `<tr class="group-divider-row"><td colspan="${totalColumns}"><div class="group-divider-label">${escapeHtml(themeLabel)}</div></td></tr>`;
    }
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
  installSerenitySelectionControls(stocks);
  hydrateInlineKlines(stocks);
}

function renderLowBase(parsed) {
  const stocks = parsed.stocks;
  if (!stocks.length) {
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = `
      <div class="summary-grid">${buildSummaryChips({
        '交易日': parsed.summary.date,
        '市場60日中位數': parsed.summary.marketMedian,
        '評估母體': parsed.summary.universe,
        '入選數量': parsed.summary.count,
      })}</div>
      <div class="empty-block">目前沒有同時符合「市場相對低基期＋近期轉強」的股票。</div>`;
    return;
  }

  const intradayMap = getIntradayMap();
  const showIntradayColumns = isIntradayFunction();
  const maxFutureDays = Math.max(...stocks.map((stock) => stock.futureDays.length));
  let html = `<div class="summary-grid">${buildSummaryChips({
    '交易日': parsed.summary.date,
    '市場60日中位數': parsed.summary.marketMedian,
    '評估母體': parsed.summary.universe,
    '入選數量': parsed.summary.count,
    '判斷方式': '市場相對排名，不看一年低點',
  })}</div>`;
  html += '<div class="table-wrapper"><table class="stock-table"><thead><tr>';
  html += '<th>等級</th><th style="text-align:right">分數</th><th>代號</th><th>名稱</th><th>族群</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">收盤</th><th style="text-align:right">成交量</th><th style="text-align:right">60日漲幅</th><th style="text-align:right">市場百分位</th><th style="text-align:right">族群差</th><th style="text-align:right">5日轉強</th><th style="text-align:right">量比</th>';
  if (showIntradayColumns) html += '<th style="text-align:center">即時價</th><th style="text-align:right">即時量</th>';
  if (maxFutureDays > 0) {
    for (const day of stocks.find((stock) => stock.futureDays.length === maxFutureDays).futureDays) {
      html += `<th style="text-align:center">${escapeHtml(formatYmd(day.date).slice(5))}</th>`;
    }
  }
  html += '</tr></thead><tbody>';

  for (const stock of stocks) {
    const intraday = intradayMap[stock.code] || {};
    html += '<tr>';
    html += `<td><span class="grade-pill ${gradeTone(stock.grade)}">${escapeHtml(stock.grade)}</span></td>`;
    html += `<td class="td-number td-score">${escapeHtml(stock.rankScore)}</td>`;
    html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
    html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
    html += `<td><span class="theme-pill">${escapeHtml(stock.theme)}</span></td>`;
    html += buildInlineKlineSlot(stock);
    html += `<td class="td-number">${escapeHtml(stock.close)}</td>`;
    html += `<td class="td-number">${escapeHtml(stock.volume)}</td>`;
    html += `<td class="td-number ${toneClassFromNumber(stock.return60d)}">${escapeHtml(stock.return60d)}%</td>`;
    html += `<td class="td-number">${escapeHtml(stock.marketPercentile)}</td>`;
    html += `<td class="td-number ${toneClassFromNumber(stock.sectorRelative)}">${escapeHtml(stock.sectorRelative)}%</td>`;
    html += `<td class="td-number up-text">${escapeHtml(stock.rebound5d)}%</td>`;
    html += `<td class="td-number up-text">${escapeHtml(stock.volumeRatio)}倍</td>`;
    if (showIntradayColumns) {
      const intradayTone = toneClassFromNumber(intraday.change_percent);
      html += `<td class="td-future td-intraday ${intradayTone}">${intraday.error ? '—' : `<strong>${formatPrice(intraday.last_price)}</strong><span>${formatChangePercent(intraday.change_percent)}</span>`}</td>`;
      html += `<td class="td-number">${intraday.error ? '—' : formatVolume(intraday.trade_volume)}</td>`;
    }
    for (const day of stock.futureDays) {
      const tone = day.pctFromPrev.startsWith('+') ? 'up-text' : day.pctFromPrev.startsWith('-') ? 'down-text' : '';
      html += `<td class="td-future"><strong>${escapeHtml(day.close)}</strong><span class="${tone}">${escapeHtml(day.pctFromPrev)}</span></td>`;
    }
    for (let index = stock.futureDays.length; index < maxFutureDays; index++) html += '<td class="td-future td-empty">—</td>';
    html += '</tr>';
  }
  html += '</tbody></table></div>';
  elements.latestOutput.className = 'output-box rich-output';
  elements.latestOutput.innerHTML = html;
  installSerenitySelectionControls(stocks);
  hydrateInlineKlines(stocks);
}

function renderPreBreakoutIntraday(parsed, stocks, intradaySummary, quoteDateLabel, quoteVolumeLabel) {
  const groupedStocks = parsed.sector ? enrichMaBullishStocks(stocks, parsed.sector) : stocks;
  const totalColumns = (parsed.sector ? 1 : 0) + 10;
  const statusText = `${intradaySummary.matched_count}/${intradaySummary.count} 符合｜${compactTimestamp(intradaySummary.finished_at)}`;
  let html = `<div class="summary-grid">${buildSummaryChips({
    '交易日': intradaySummary.result_date,
    '來源完整日': intradaySummary.source_result_date,
    '入選數量': intradaySummary.matched_count,
    '即時行情': statusText,
  })}</div>`;

  if (!groupedStocks.length) {
    html += '<div class="empty-block">目前盤中沒有符合標準選股 A 級條件的股票。</div>';
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = html;
    return;
  }

  html += '<div class="table-wrapper"><table class="stock-table"><thead><tr>';
  if (parsed.sector) html += '<th>族群</th>';
  html += `<th>等級</th><th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th class="th-name" style="text-align:left">名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">${escapeHtml(quoteDateLabel)}</th><th style="text-align:right">${escapeHtml(quoteVolumeLabel)}</th><th style="text-align:right">MA5</th><th style="text-align:right">MA10</th><th>狀態</th>`;
  html += '</tr></thead><tbody>';

  let currentTheme = null;
  for (const stock of groupedStocks) {
    const tone = gradeTone(stock.grade);
    if (parsed.sector && stock.themeName && stock.themeName !== currentTheme) {
      currentTheme = stock.themeName;
      const themeMeta = parsed.sector.themeRows.find((row) => row.themeName === stock.themeName);
      const themeLabel = themeMeta ? `${themeMeta.themeName}｜${themeMeta.count} 檔` : stock.themeName;
      html += `<tr class="group-divider-row"><td colspan="${totalColumns}"><div class="group-divider-label">${escapeHtml(themeLabel)}</div></td></tr>`;
    }
    const intradayTone = toneClassFromNumber(stock.change_percent);
    html += '<tr>';
    if (parsed.sector) html += `<td class="td-theme"><span class="theme-pill">${escapeHtml(stock.themeName || '—')}</span></td>`;
    html += `<td class="td-grade"><span class="grade-pill ${tone}">${escapeHtml(stock.grade || 'A')}</span></td>`;
    html += `<td class="td-number td-score">${escapeHtml(stock.rankScore || stock.rank_score || '—')}</td>`;
    html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
    html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
    html += buildInlineKlineSlot(stock);
    html += `<td class="td-future td-intraday ${intradayTone}"><strong>${formatPrice(stock.last_price)}</strong><span class="${intradayTone}">${escapeHtml(formatChangePercent(stock.change_percent))}</span></td>`;
    html += `<td class="td-number">${formatVolume(stock.trade_volume)}</td>`;
    html += `<td class="td-number">${formatPrice(stock.ma5)}</td>`;
    html += `<td class="td-number">${formatPrice(stock.ma10)}</td>`;
    html += '<td><span class="status-pill success">盤中符合</span></td>';
    html += '</tr>';
  }

  html += '</tbody></table></div>';
  elements.latestOutput.className = 'output-box rich-output';
  elements.latestOutput.innerHTML = html;
  installSerenitySelectionControls(groupedStocks);
  hydrateInlineKlines(groupedStocks);
}

function renderPreBreakout(parsed) {
  const stocks = parsed.sector ? enrichMaBullishStocks(parsed.stocks, parsed.sector) : parsed.stocks;
  const institutionalMap = getInstitutionalMap();
  const institutionalSummary = state.currentRun?.institutional?.payload;
  const intradayMap = getIntradayMap();
  const intradaySummary = state.currentRun?.intraday?.payload;
  const currentIntradayRun = Boolean(state.currentRun?.current_intraday);
  const quoteDateLabel = intradaySummary?.quote_date ? `${formatYmd(intradaySummary.quote_date)}股價` : '即時價';
  const quoteVolumeLabel = intradaySummary?.quote_date ? `${formatYmd(intradaySummary.quote_date)}量` : '即時量';
  const showIntradayColumns = isIntradayFunction();

  if (currentIntradayRun && intradaySummary) {
    const candidateMap = new Map(parsed.stocks.map((stock) => [stock.code, stock]));
    const liveStocks = Object.values(intradayMap)
      .filter((quote) => quote?.matched === true)
      .map((quote) => ({
        ...(candidateMap.get(quote.code) || {}),
        ...quote,
        rankScore: quote.rank_score || candidateMap.get(quote.code)?.rankScore || '',
        close: quote.last_price ?? candidateMap.get(quote.code)?.close ?? '',
        volume: quote.trade_volume ?? candidateMap.get(quote.code)?.volume ?? '',
      }));
    renderPreBreakoutIntraday(parsed, liveStocks, intradaySummary, quoteDateLabel, quoteVolumeLabel);
    return;
  }

  if (!stocks.length) {
    elements.latestOutput.className = 'output-box rich-output';
    elements.latestOutput.innerHTML = `
      <div class="summary-grid">${buildSummaryChips({ '交易日': parsed.summary.date, '市場熱度': parsed.summary.heat, '入選數量': parsed.summary.count })}</div>
      <div class="empty-block">沒有可顯示的股票。</div>`;
    return;
  }

  const maxFutureDays = Math.max(...stocks.map((s) => s.futureDays.length));
  const totalColumns = (parsed.sector ? 1 : 0) + 8 + (showIntradayColumns ? 2 : 0) + (maxFutureDays > 0 ? maxFutureDays + 1 : 0);
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
  if (parsed.sector) html += '<th>族群</th>';
  html += '<th>等級</th><th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th class="th-name" style="text-align:left">名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">收盤</th><th style="text-align:right">成交量</th>';
  if (showIntradayColumns) {
    html += `<th style="text-align:center">${escapeHtml(quoteDateLabel)}</th><th style="text-align:right">${escapeHtml(quoteVolumeLabel)}</th>`;
  }
  html += '<th style="text-align:right">法人合計</th>';

  if (maxFutureDays > 0 && stocks[0].futureDays.length > 0) {
    for (const day of stocks[0].futureDays) {
      html += `<th style="text-align:center">${escapeHtml(formatYmd(day.date).slice(5))}</th>`;
    }
    html += '<th style="text-align:center">合計%</th>';
  }
  html += '</tr></thead><tbody>';

  let currentTheme = null;
  for (const stock of stocks) {
    const tone = gradeTone(stock.grade);
    const inst = institutionalMap[stock.code] || {};
    const intraday = intradayMap[stock.code] || {};
    if (parsed.sector && stock.themeName && stock.themeName !== currentTheme) {
      currentTheme = stock.themeName;
      const themeMeta = parsed.sector.themeRows.find((row) => row.themeName === stock.themeName);
      const themeLabel = themeMeta ? `${themeMeta.themeName}｜${themeMeta.count} 檔` : stock.themeName;
      html += `<tr class="group-divider-row"><td colspan="${totalColumns}"><div class="group-divider-label">${escapeHtml(themeLabel)}</div></td></tr>`;
    }
    html += '<tr>';
    if (parsed.sector) {
      html += `<td class="td-theme"><span class="theme-pill">${escapeHtml(stock.themeName || '—')}</span></td>`;
    }
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
  installSerenitySelectionControls(stocks);
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
  installSerenitySelectionControls(stocks);
  hydrateInlineKlines(stocks);
}

function customSectorStockForMaColumns(stock) {
  return {
    ...stock,
    rankScore: stock.rankScore || '—',
    close: stock.close || '—',
    volume: stock.volume ? `${floorVolumeText(stock.volume)}` : '—',
    multiple: stock.multiple || '—',
    futureDays: Array.isArray(stock.futureDays) ? stock.futureDays : [],
  };
}

function customSectorGroupId(groupIndex) {
  return `custom-sector-group-${groupIndex}`;
}

function renderCustomSectorRanking(rankings) {
  const items = Array.isArray(rankings) ? rankings.slice(0, 10) : [];
  if (!items.length) return '';
  let html = '<section class="custom-sector-ranking" aria-label="族群排名">';
  html += '<div class="custom-sector-ranking-heading"><h3>族群排名</h3><span>依個股平均排序分數</span></div>';
  html += '<div class="custom-sector-ranking-list">';
  for (const item of items) {
    const averageScore = Number(item.averageRankScore);
    const scoreText = Number.isFinite(averageScore) ? averageScore.toFixed(2) : '—';
    const targetId = customSectorGroupId(item.groupIndex);
    html += `<button type="button" class="custom-sector-rank-item" data-custom-sector-target="${escapeHtml(targetId)}" title="移到${escapeHtml(item.name)}族群">
      <span class="custom-sector-rank-number">${escapeHtml(item.rank)}</span>
      <span class="custom-sector-rank-name">${escapeHtml(item.name)}</span>
      <span class="custom-sector-rank-score">平均 ${escapeHtml(scoreText)}</span>
      <span class="custom-sector-rank-count">${escapeHtml(item.count)} 檔</span>
    </button>`;
  }
  html += '</div></section>';
  return html;
}

function bindCustomSectorRankingJump() {
  document.querySelectorAll('.custom-sector-rank-item').forEach((button) => {
    button.addEventListener('click', () => {
      const target = document.getElementById(button.dataset.customSectorTarget || '');
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      target.classList.remove('custom-sector-highlight');
      window.requestAnimationFrame(() => target.classList.add('custom-sector-highlight'));
      window.setTimeout(() => target.classList.remove('custom-sector-highlight'), 1600);
    });
  });
}

function renderCustomSectorTable(group, groupIndex) {
  const stocks = (group.stocks || []).map(customSectorStockForMaColumns);
  const maxFutureDays = Math.min(5, Math.max(0, ...stocks.map((stock) => stock.futureDays.length)));
  let html = `<section id="${customSectorGroupId(groupIndex)}" class="custom-sector-block"><div class="custom-sector-heading"><h3>${escapeHtml(group.name)}</h3><span>${escapeHtml(group.count ?? stocks.length)} 檔</span></div>`;
  if (!stocks.length) {
    return `${html}<div class="empty-block">這個族群在選定日期沒有可用資料。</div></section>`;
  }

  html += '<div class="table-wrapper"><table class="stock-table"><thead><tr>';
  html += '<th>族群</th><th class="th-score" style="text-align:right">排序分數</th><th>代號</th><th>名稱</th><th class="th-mini-kline">40日K線</th><th style="text-align:right">收盤</th><th style="text-align:right">成交量</th><th style="text-align:right">量能倍數</th>';
  if (maxFutureDays > 0) {
    const headerStock = stocks.find((stock) => stock.futureDays.length >= maxFutureDays);
    for (const day of (headerStock?.futureDays || []).slice(0, maxFutureDays)) {
      html += `<th style="text-align:center">${escapeHtml(formatYmd(day.date).slice(5))}</th>`;
    }
    html += '<th style="text-align:center">合計%</th>';
  }
  html += '</tr></thead><tbody>';

  for (const stock of stocks) {
    html += '<tr>';
    html += `<td class="td-theme"><span class="theme-pill">${escapeHtml(group.name)}</span></td>`;
    html += `<td class="td-number td-score">${escapeHtml(stock.rankScore)}</td>`;
    html += `<td class="td-code">${buildCodeButton(stock)}</td>`;
    html += `<td class="td-name">${escapeHtml(stock.name)}</td>`;
    html += buildInlineKlineSlot(stock);
    html += `<td class="td-number">${escapeHtml(stock.close)}</td>`;
    html += `<td class="td-number">${escapeHtml(stock.volume)}</td>`;
    html += `<td class="td-number up-text">${escapeHtml(stock.multiple)}${stock.multiple !== '—' ? '倍' : ''}</td>`;
    if (maxFutureDays > 0) {
      for (let index = 0; index < maxFutureDays; index += 1) {
        const day = stock.futureDays[index];
        if (!day) {
          html += '<td class="td-future td-empty">—</td>';
          continue;
        }
        const tone = day.pctFromPrev.startsWith('+') ? 'up-text' : day.pctFromPrev.startsWith('-') ? 'down-text' : '';
        html += `<td class="td-future"><strong>${escapeHtml(day.close)}</strong><span class="${tone}">${escapeHtml(day.pctFromPrev)}</span></td>`;
      }
      const lastDay = stock.futureDays[Math.min(stock.futureDays.length, maxFutureDays) - 1];
      html += lastDay
        ? `<td class="td-future td-total"><span class="${lastDay.pctFromSignal.startsWith('+') ? 'up-text' : lastDay.pctFromSignal.startsWith('-') ? 'down-text' : ''}">${escapeHtml(lastDay.pctFromSignal)}</span></td>`
        : '<td class="td-future td-empty">—</td>';
    }
    html += '</tr>';
  }
  html += `</tbody></table></div></section>`;
  return html;
}

function renderCustomSectors(payload) {
  state.currentRun = null;
  elements.latestMeta.innerHTML = '';
  elements.artifactList.innerHTML = '';
  const metaItems = [
    ['交易日', formatYmd(payload.result_date)],
    ['族群數量', `${payload.group_count || 0} 組`],
    ['股票數量', `${payload.stock_count || 0} 檔`],
    ['資料來源', '手動自訂族群清單'],
  ];
  for (const [label, value] of metaItems) {
    const div = document.createElement('div');
    div.className = 'meta-item';
    div.textContent = `${label}：${value}`;
    elements.latestMeta.appendChild(div);
  }

  const groups = Array.isArray(payload.groups) ? payload.groups : [];
  const rankingHtml = renderCustomSectorRanking(payload.rankings);
  const groupHtml = groups.map((group, groupIndex) => renderCustomSectorTable(group, groupIndex)).join('');
  elements.latestOutput.className = 'output-box rich-output custom-sector-output';
  elements.latestOutput.innerHTML = rankingHtml + (groupHtml || '<div class="empty-block">目前沒有可顯示的自訂股票族群。</div>');
  bindCustomSectorRankingJump();
  const allStocks = groups.flatMap((group) => group.stocks || []).map(customSectorStockForMaColumns);
  hydrateInlineKlines(allStocks);
  setStatus(groups.length ? '自訂族群已載入' : '沒有自訂族群資料', groups.length ? 'success' : 'neutral');
}

function renderOutput(run) {
  const text = run.output_text || '(無輸出)';
  const parsedNewHighBlack = parseNewHighBlackOutput(text);
  if (parsedNewHighBlack && run.status === 'success') {
    renderNewHighBlack(parsedNewHighBlack);
    return;
  }

  const parsedLowBase = parseLowBaseOutput(text);
  if (parsedLowBase && run.status === 'success') {
    renderLowBase(parsedLowBase);
    return;
  }

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

function chipStockButton(item) {
  return `<button type="button" class="chip-stock-link" data-chip-code="${escapeHtml(item.code)}">${escapeHtml(item.code)} ${escapeHtml(item.name || '')}</button>`;
}

function chipEmpty(message) {
  return `<div class="chip-empty">${escapeHtml(message || '目前沒有資料。')}</div>`;
}

function renderChipRankingRows(items, emptyMessage) {
  if (!items?.length) return chipEmpty(emptyMessage);
  const maxAbs = Math.max(...items.map((item) => Math.abs(Number(item.change_rate) || 0)), 0.01);
  return `<div class="chip-table-wrap"><table class="chip-table"><thead><tr><th>排名</th><th>股票</th><th>產業</th><th>本週變化</th><th>連續</th></tr></thead><tbody>${items.map((item, index) => {
    const streak = Number(item.change_rate) >= 0 ? item.consecutive_increase : item.consecutive_decrease;
    const width = Math.max(4, Math.abs(Number(item.change_rate) || 0) / maxAbs * 100);
    return `<tr><td>${index + 1}</td><td>${chipStockButton(item)}<small>${escapeHtml(item.market || '')}</small></td><td>${escapeHtml(item.industry || '未分類')}</td><td class="${toneClassFromNumber(item.change_rate)}"><strong>${formatSignedPercent(item.change_rate)}</strong><small>占比 ${formatPercentagePoints(item.ratio_change_pp)}</small><span class="chip-strength-bar"><i style="width:${width.toFixed(1)}%"></i></span></td><td>${Number(streak || 0)} 週</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function renderChipIndustryRows(items) {
  if (!items?.length) return chipEmpty('目前至少需要兩週全市場集保資料，才能計算族群強弱。');
  return `<div class="chip-table-wrap"><table class="chip-table"><thead><tr><th>排名</th><th>族群</th><th>分數</th><th>週增減率中位數</th><th>增加比例</th><th>領先股票</th></tr></thead><tbody>${items.map((item) => `<tr><td>${item.rank}</td><td><strong>${escapeHtml(item.industry)}</strong><small>${item.valid_count} 檔有效成員</small></td><td>${Number(item.score).toFixed(1)}</td><td class="${toneClassFromNumber(item.median_change_rate)}">${formatSignedPercent(item.median_change_rate)}</td><td>${Number(item.increase_ratio).toFixed(1)}%</td><td>${chipStockButton(item.leader || {})}</td></tr>`).join('')}</tbody></table></div>`;
}

function renderChipFeatured(items) {
  if (!items?.length) return chipEmpty('累積第二週集保資料後，系統會依透明規則產生熱門股票卡。');
  return items.map((item) => `<button type="button" class="chip-featured-card" data-chip-code="${escapeHtml(item.code)}"><span>${escapeHtml(item.industry || '未分類')}</span><strong>${escapeHtml(item.name)} ${escapeHtml(item.code)}</strong><em class="${toneClassFromNumber(item.change_rate)}">${formatSignedPercent(item.change_rate)}</em><small>有效母體第 ${item.market_rank || '—'} 名 · 連續增加 ${item.consecutive_increase || 0} 週</small></button>`).join('');
}

function renderChipStockAnalysis(payload) {
  const mount = document.getElementById('chip-stock-analysis');
  if (!mount) return;
  const stock = payload.stock || {};
  const summary = payload.summary;
  const history = payload.history || [];
  const institutional = payload.institutional || [];
  const peers = payload.industry_comparison || [];
  const maxHistory = Math.max(...history.map((item) => Math.abs(Number(item.change_rate) || 0)), 0.01);
  mount.hidden = false;
  mount.innerHTML = `
    <div class="chip-section-heading"><div><p class="eyebrow">Stock analysis</p><h3>${escapeHtml(stock.name)} ${escapeHtml(stock.code)}</h3></div><span>${escapeHtml(stock.market || '')} · ${escapeHtml(stock.industry || '未分類')} · 資料週 ${formatYmd(payload.data_date)}</span></div>
    ${summary ? `<div class="chip-summary-grid"><div><span>本週籌碼增減率</span><strong class="${toneClassFromNumber(summary.change_rate)}">${formatSignedPercent(summary.change_rate)}</strong></div><div><span>持股占比變化</span><strong class="${toneClassFromNumber(summary.ratio_change_pp)}">${formatPercentagePoints(summary.ratio_change_pp)}</strong></div><div><span>大戶持股占比</span><strong>${Number(summary.large_holder_ratio).toFixed(2)}%</strong></div><div><span>有效母體／族群排名</span><strong>${summary.market_rank || '—'}／${summary.industry_rank || '—'}</strong></div></div>` : chipEmpty('這檔股票目前沒有集保資料。')}
    <div class="chip-two-column">
      <article><h4>近 9 週籌碼變化</h4><div class="chip-history-chart">${history.map((item) => { const value = Number(item.change_rate); const height = Number.isFinite(value) ? Math.max(3, Math.abs(value) / maxHistory * 100) : 3; return `<div class="chip-history-column"><span class="${toneClassFromNumber(value)}">${formatSignedPercent(value)}</span><i class="${value > 0 ? 'up' : value < 0 ? 'down' : 'flat'}" style="height:${height.toFixed(1)}%"></i><small>${formatYmd(item.data_date).slice(5)}</small></div>`; }).join('')}</div>${payload.history_complete ? '' : '<p class="chip-data-note">歷史資料尚未滿 9 週，畫面顯示目前可取得的週數。</p>'}</article>
      <article><h4>三大法人近期明細</h4>${institutional.length ? `<div class="chip-table-wrap"><table class="chip-table"><thead><tr><th>日期</th><th>外資</th><th>投信</th><th>自營商</th><th>合計／占量比</th></tr></thead><tbody>${institutional.map((row) => `<tr><td>${formatYmd(row.trade_date)}</td><td>${Number(row.foreign_lots).toLocaleString('zh-TW')}</td><td>${Number(row.investment_trust_lots).toLocaleString('zh-TW')}</td><td>${Number(row.dealer_lots).toLocaleString('zh-TW')}</td><td class="${toneClassFromNumber(row.total_lots)}">${Number(row.total_lots).toLocaleString('zh-TW')} 張／${formatSignedPercent(row.volume_ratio)}</td></tr>`).join('')}</tbody></table></div>` : chipEmpty('法人每日快照尚未匯入；不以其他口徑資料替代。')}</article>
    </div>
    <article><h4>同族群股票籌碼比較</h4>${renderChipRankingRows(peers, '族群比較需要至少兩週有效集保資料。')}</article>`;
  mount.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function loadChipStock(code) {
  const mount = document.getElementById('chip-stock-analysis');
  if (mount) {
    mount.hidden = false;
    mount.innerHTML = chipEmpty(`正在載入 ${code} 的近 9 週資料，首次查詢會稍久一些...`);
  }
  setStatus('個股籌碼載入中...', 'running');
  const response = await fetch(`/api/chips/stocks/${encodeURIComponent(code)}`);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) throw new Error(payload.error || '個股籌碼載入失敗');
  renderChipStockAnalysis(payload);
  setStatus('個股籌碼已載入', 'success');
}

function bindChipDashboardEvents() {
  const form = document.getElementById('chip-search-form');
  const input = document.getElementById('chip-search-input');
  const suggestions = document.getElementById('chip-search-suggestions');
  let searchTimer = null;
  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (query.length < 2) return;
    if (/^\d{4}$/.test(query)) { await loadChipStock(query); return; }
    const response = await fetch(`/api/chips/stocks/search?q=${encodeURIComponent(query)}`);
    const payload = await response.json();
    if (payload.items?.[0]) await loadChipStock(payload.items[0].code);
    else throw new Error('找不到符合的上市／上櫃普通股。');
  });
  input?.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    const query = input.value.trim();
    if (query.length < 2) { suggestions.hidden = true; suggestions.innerHTML = ''; return; }
    searchTimer = window.setTimeout(async () => {
      const response = await fetch(`/api/chips/stocks/search?q=${encodeURIComponent(query)}`);
      const payload = await response.json();
      suggestions.innerHTML = (payload.items || []).map((item) => `<button type="button" data-chip-suggestion="${escapeHtml(item.code)}"><strong>${escapeHtml(item.code)} ${escapeHtml(item.name)}</strong><span>${escapeHtml(item.market)} · ${escapeHtml(item.industry)}</span></button>`).join('');
      suggestions.hidden = !payload.items?.length;
    }, 220);
  });
  suggestions?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-chip-suggestion]');
    if (!button) return;
    suggestions.hidden = true;
    input.value = button.dataset.chipSuggestion;
    loadChipStock(button.dataset.chipSuggestion).catch((error) => setStatus(String(error.message || error), 'failed'));
  });
  document.querySelector('.chip-dashboard')?.addEventListener('click', (event) => {
    const stock = event.target.closest('[data-chip-code]');
    if (stock) loadChipStock(stock.dataset.chipCode).catch((error) => setStatus(String(error.message || error), 'failed'));
    const tab = event.target.closest('[data-chip-tab]');
    if (tab) {
      document.querySelectorAll('[data-chip-tab]').forEach((item) => item.classList.toggle('active', item === tab));
      document.querySelector('.chip-ranking-grid')?.setAttribute('data-active-tab', tab.dataset.chipTab);
    }
  });
}

function renderChipDashboard(rankings, industries, featured) {
  const template = document.getElementById('chip-dashboard-template');
  elements.latestOutput.className = 'output-box chip-dashboard-output';
  elements.latestOutput.innerHTML = '';
  elements.latestOutput.appendChild(template.content.cloneNode(true));
  document.getElementById('chip-ranking-date').textContent = `資料週 ${formatYmd(rankings.data_date)} · 有效比較母體 ${Number(rankings.comparison_stock_count || 0).toLocaleString('zh-TW')} 檔`;
  const noRankingMessage = rankings.message || '目前沒有符合條件的股票。';
  document.getElementById('chip-increase-ranking').innerHTML = renderChipRankingRows(rankings.increase, noRankingMessage);
  document.getElementById('chip-decrease-ranking').innerHTML = renderChipRankingRows(rankings.decrease, noRankingMessage);
  document.getElementById('chip-industry-ranking').innerHTML = renderChipIndustryRows(industries.items);
  document.getElementById('chip-featured-cards').innerHTML = renderChipFeatured(featured.items);
  bindChipDashboardEvents();
}

async function loadChipDashboard() {
  elements.latestMeta.innerHTML = '';
  elements.artifactList.innerHTML = '';
  elements.latestOutput.className = 'output-box empty';
  elements.latestOutput.textContent = '正在同步官方集保與產業資料，首次載入可能需要一些時間...';
  setStatus('籌碼資料載入中...', 'running');
  const [rankingsResponse, industriesResponse, featuredResponse] = await Promise.all([
    fetch('/api/chips/rankings'), fetch('/api/chips/industries'), fetch('/api/chips/featured'),
  ]);
  const [rankings, industries, featured] = await Promise.all([
    rankingsResponse.json(), industriesResponse.json(), featuredResponse.json(),
  ]);
  if (!rankingsResponse.ok || !rankings.ok) throw new Error(rankings.error || '排行榜載入失敗');
  if (!industriesResponse.ok || !industries.ok) throw new Error(industries.error || '族群排名載入失敗');
  if (!featuredResponse.ok || !featured.ok) throw new Error(featured.error || '熱門股票載入失敗');
  renderChipDashboard(rankings, industries, featured);
  elements.latestMeta.innerHTML = `<div class="meta-item">集保資料週：${formatYmd(rankings.data_date)}</div><div class="meta-item">有效比較母體：${Number(rankings.comparison_stock_count || 0).toLocaleString('zh-TW')} 檔</div><div class="meta-item">來源：TDCC 公開資料</div><div class="meta-item">計算版本：${escapeHtml(rankings.calculation_version)}</div>`;
  setStatus('籌碼儀表板已載入', 'success');
}

async function loadCurrentResult() {
  if (isChipDashboardFunction()) {
    await loadChipDashboard();
    return;
  }
  if (isCustomSectorFunction()) {
    await loadCustomSectors();
    return;
  }
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
  await loadSerenityCache();
}

async function loadCustomSectors() {
  if (!state.selectedDate) {
    elements.latestOutput.className = 'output-box empty';
    elements.latestOutput.innerHTML = '目前沒有可用交易日。';
    setStatus('待命', 'neutral');
    return;
  }

  elements.latestMeta.innerHTML = '';
  elements.artifactList.innerHTML = '';
  elements.latestOutput.className = 'output-box empty';
  elements.latestOutput.innerHTML = '正在載入自訂股票族群，請稍候...';
  setStatus('載入自訂族群中...', 'running');
  const query = new URLSearchParams({ result_date: state.selectedDate });
  const response = await fetch(`/api/custom_sectors?${query.toString()}`);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || '讀取自訂股票族群失敗');
  }
  renderCustomSectors(payload);
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
  if (isChipDashboardFunction()) {
    await loadChipDashboard();
    return;
  }
  if (isFearGreedFunction()) {
    await loadFearGreedStatus(true);
    return;
  }
  if (isCustomSectorFunction()) {
    await loadCustomSectors();
    return;
  }
  await loadCurrentResult();
}

function currentBacktestParams() {
  return {
    start_date: fromInputDate(elements.backtestStartDate.value), end_date: fromInputDate(elements.backtestEndDate.value),
    take_profit_pct: Number(elements.backtestTp.value), stop_loss_pct: Number(elements.backtestSl.value),
    entry_max_pct: Number(elements.backtestEntryMax.value), entry_min_pct: Number(elements.backtestEntryMin.value),
    top_n: Number(elements.backtestTopN.value), total_capital: Number(elements.backtestTotalCapital.value),
    max_hold_days: Number(elements.backtestMaxHoldDays.value),
  };
}

function applyBacktestPreset(preset) {
  const p = preset.params || {};
  const fields = { start_date: elements.backtestStartDate, end_date: elements.backtestEndDate, take_profit_pct: elements.backtestTp, stop_loss_pct: elements.backtestSl, entry_max_pct: elements.backtestEntryMax, entry_min_pct: elements.backtestEntryMin, top_n: elements.backtestTopN, total_capital: elements.backtestTotalCapital, max_hold_days: elements.backtestMaxHoldDays };
  for (const [key, field] of Object.entries(fields)) {
    if (p[key] !== undefined && p[key] !== null) field.value = key.endsWith('_date') ? toInputDate(String(p[key])) : p[key];
  }
  elements.backtestPresetDescription.value = preset.description;
  setBacktestStatus('已套用條件', 'success');
}

function renderBacktestPresets() {
  const selected = elements.backtestPresetSelect.value;
  elements.backtestPresetSelect.innerHTML = '<option value="">選擇已儲存的回測條件</option>' + state.backtestPresets.map((p) => `<option value="${p.id}">${escapeHtml(p.description)}</option>`).join('');
  elements.backtestPresetSelect.value = selected;
  elements.backtestPresetDeleteButton.disabled = !elements.backtestPresetSelect.value;
}

async function loadBacktestPresets() {
  const response = await fetch('/api/backtest-presets');
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || '讀取回測條件失敗');
  state.backtestPresets = payload.presets || [];
  renderBacktestPresets();
}

async function saveBacktestPreset() {
  const description = elements.backtestPresetDescription.value.trim();
  if (!description) { setBacktestStatus('請輸入條件說明', 'failed'); return; }
  const response = await fetch('/api/backtest-presets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ description, params: currentBacktestParams() }) });
  const payload = await response.json();
  if (!response.ok) { setBacktestStatus(payload.error || '儲存失敗', 'failed'); return; }
  await loadBacktestPresets();
  elements.backtestPresetSelect.value = String(payload.preset.id);
  elements.backtestPresetDeleteButton.disabled = false;
  setBacktestStatus('條件已儲存', 'success');
}

async function deleteBacktestPreset() {
  const id = elements.backtestPresetSelect.value;
  if (!id) return;
  const response = await fetch(`/api/backtest-presets/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!response.ok) { setBacktestStatus('刪除失敗', 'failed'); return; }
  await loadBacktestPresets();
  elements.backtestPresetDescription.value = '';
  setBacktestStatus('條件已刪除', 'success');
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
  const totalCapital = Number(elements.backtestTotalCapital.value);
  const maxHoldDays = Number(elements.backtestMaxHoldDays.value);

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
  if (!Number.isFinite(totalCapital) || totalCapital <= 0) {
    renderBacktestEmpty('每次訊號總投入金額請輸入大於 0 的數字。');
    setBacktestStatus('參數錯誤', 'failed');
    return;
  }
  if (!Number.isInteger(maxHoldDays) || maxHoldDays <= 0) {
    renderBacktestEmpty('最多持有天數請輸入大於 0 的整數。');
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
        max_hold_days: maxHoldDays,
        total_capital: totalCapital,
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

async function runSerenityAnalysis(forceRefresh = false) {
  forceRefresh = forceRefresh === true;
  if (!state.selectedFunction?.executable) return;
  const stocks = getSelectedSerenityStocks();
  if (!stocks.length) {
    resetSerenityPanel('請先在結果表勾選至少 1 檔股票，再執行 Serenity 深度分析。');
    setSerenityStatus('沒有勾選股票', 'failed');
    return;
  }
  const selectionChanged = !sameStockCodeSet(
    stocks.map((stock) => stock.code),
    state.serenityAnalyzedCodes,
  );

  const progressSteps = [
    '啟動快速研究代理...',
    '平行查詢公開資料...',
    '核對產業鏈與瓶頸證據...',
    '整理風險與反方條件...',
    '產生精簡研究報告...',
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
        force_refresh: forceRefresh || selectionChanged,
        stock_codes: stocks.map((stock) => stock.code),
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || 'Serenity 深度分析失敗');
    }

    renderSerenityResult(payload);
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
  if (key === 'new_high_black_volume_contraction' && state.intradayDate) {
    state.selectedDate = state.intradayDate;
    localStorage.setItem('stock-control-date', state.selectedDate);
  } else if (key === 'pre_breakout_standard' && state.intradayDate) {
    state.selectedDate = state.intradayDate;
    localStorage.setItem('stock-control-date', state.selectedDate);
  } else if (!isDirectCurrentIntradayFunction(key) && state.selectedDate === state.intradayDate) {
    state.selectedDate = state.dates[0] || '';
    if (state.selectedDate) localStorage.setItem('stock-control-date', state.selectedDate);
  }
  state.selectedFunction = state.functions.find((item) => item.key === key) || null;
  state.currentRun = null;
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

  if (isCustomSectorFunction()) {
    await loadCustomSectors();
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

  if (isCurrentIntradaySelection() && !(await ensureTokenConfigured('fugle'))) return;

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
  const shouldRefreshSerenity = Boolean(state.serenityResult);

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
    if (shouldRefreshSerenity) {
      await runSerenityAnalysis(true);
    }
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
      if (payload.current_intraday) {
        state.currentRun.current_intraday = true;
        state.currentRun.result_date = payload.payload?.result_date || state.selectedDate;
        state.currentRun.status = payload.status;
      }
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

async function loadDatesInBackground() {
  try {
    const response = await fetch('/api/dates');
    const datePayload = await response.json();
    if (!response.ok) {
      throw new Error(datePayload.error || '讀取交易日失敗');
    }
    state.dates = datePayload.dates || [];
    state.intradayDate = datePayload.intraday_date || '';
    if (datePayload.sync_status?.fetched) {
      setStatus('已自動補抓最新資料', 'success');
    } else if (datePayload.sync_status?.status === 'failed') {
      setStatus('最新資料補抓失敗', 'failed');
    } else {
      setStatus('交易日資料已載入', 'success');
    }
    if (state.intradayDate && isDirectCurrentIntradayFunction()) {
      state.selectedDate = state.intradayDate;
      localStorage.setItem('stock-control-date', state.selectedDate);
    } else if (!state.selectedDate || !isSelectableDate(state.selectedDate)) {
      state.selectedDate = datePayload.latest_date || '';
      if (state.selectedDate) {
        localStorage.setItem('stock-control-date', state.selectedDate);
      }
    }
    renderDateOptions();
    renderActionButtons();
    syncBacktestInputsFromDates();
    await selectFunction(state.selectedKey);
  } catch (error) {
    setStatus('交易日載入失敗', 'failed');
    renderPlainOutput(`交易日資料載入失敗：${String(error.message || error)}`, 'error-output');
  }
}

async function init() {
  const [functionsResponse, marketStateResponse] = await Promise.all([
    fetch('/api/functions'),
    fetch('/api/market_state'),
  ]);
  if (!functionsResponse.ok) {
    throw new Error('讀取選股功能失敗');
  }
  state.functions = await functionsResponse.json();
  state.marketState = marketStateResponse.ok ? await marketStateResponse.json() : state.marketState;
  if (!state.functions.find((item) => item.key === state.selectedKey)) {
    state.selectedKey = state.functions[0]?.key || '';
  }
  state.selectedFunction = state.functions.find((item) => item.key === state.selectedKey) || null;

  renderGroups();
  if (state.selectedFunction) {
    elements.title.textContent = state.selectedFunction.name;
    elements.description.textContent = state.selectedFunction.description;
  }
  renderDateOptions();
  renderActionButtons();
  setStatus('載入交易日資料中...', 'running');
  checkUpdateStatus();
  loadBacktestPresets().catch((error) => setBacktestStatus(String(error.message || error), 'failed'));

  elements.refreshButton.addEventListener('click', refreshCurrentView);
  elements.serenityButton.addEventListener('click', runSerenityAnalysis);
  elements.institutionalButton.addEventListener('click', runInstitutional);
  elements.intradayButton.addEventListener('click', runIntraday);
  elements.refreshFutureButton.addEventListener('click', refreshFuture);
  elements.runButton.addEventListener('click', runSelectedFunction);
  elements.backtestRunButton.addEventListener('click', runBacktest);
  elements.backtestPresetSaveButton.addEventListener('click', saveBacktestPreset);
  elements.backtestPresetDeleteButton.addEventListener('click', deleteBacktestPreset);
  elements.backtestPresetApplyButton.addEventListener('click', () => {
    const preset = state.backtestPresets.find((item) => String(item.id) === elements.backtestPresetSelect.value);
    if (preset) applyBacktestPreset(preset);
  });
  elements.backtestPresetSelect.addEventListener('change', () => {
    elements.backtestPresetDeleteButton.disabled = !elements.backtestPresetSelect.value;
  });
  elements.settingsButton.addEventListener('click', openSettingsModal);
  elements.selfUpdateButton.addEventListener('click', runSelfUpdate);
  elements.settingsClose.addEventListener('click', closeSettingsModal);
  elements.settingsForm.addEventListener('submit', saveSettings);
  elements.settingsModal.querySelector('.settings-modal-backdrop').addEventListener('click', closeSettingsModal);
  elements.klineModalClose.addEventListener('click', closeKlineModal);
  elements.klineSignalDayButton.addEventListener('click', () => renderSignalDayKline());
  elements.klineTradingViewButton.addEventListener('click', openTradingViewFullChart);
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
    openKlineModal(trigger.dataset.stockCode, trigger.dataset.stockName || '', trigger.dataset.stockMarket || '');
  });
  elements.dateInput.addEventListener('change', async (event) => {
    const nextDate = fromInputDate(event.target.value);
    if (!isSelectableDate(nextDate)) {
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

  await loadDatesInBackground();
}

init();
