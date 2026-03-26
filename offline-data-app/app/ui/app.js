/* ==========================================================================
   SOC Data Processor — Frontend (Vanilla JS, fully offline, no CDN)
   ========================================================================== */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  summary: null,           // /api/dashboard/summary response
  aggCurrentPage: 1,
  clusterCurrentPage: 1,
  splitEventSource: null,
  searchCurrentPage: 1,
  searchQuery: '',
  splitFile: null,     // file selected for standalone split
};

// Claims-specific column suggestions (normalized names after upload)
// CLAIMS NAME → claims_name, TRACKING NUMBER → tracking_number, NAME → name, HUB → hub
const SOC_DEFAULTS = {
  personKey:    'name',
  numericCols:  ['cogs_share_local'],
  dateCols:     [],
  catCols:      ['claims_name', 'hub', 'tracking_number'],
  orderCol:     'tracking_number',
  distCol1:     'hub',
  distCol2:     'claims_name',
  topGroupCol1: 'hub',
  topValCol1:   'cogs_share_local',
  topGroupCol2: 'name',
  topValCol2:   'tracking_number',
  timelineDate: null,
  statusCol:    'hub',
  clusterFeats: ['cogs_share_local'],
};

// ---------------------------------------------------------------------------
// Colour palette for charts
// ---------------------------------------------------------------------------
const PALETTE = [
  '#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f',
  '#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ac',
  '#d37295','#fabfd2','#8cd17d','#b6992d','#499894',
];

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

/** Escape a string for safe insertion into HTML. */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function apiFetch(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

function showToast(msg, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast toast-${type}`;
  el.style.display = 'block';
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.style.display = 'none'; }, 4000);
}

function buildTable(rows, maxRows = 200) {
  if (!rows || rows.length === 0) return '<p class="muted">No data.</p>';
  const slice = rows.slice(0, maxRows);
  const keys = Object.keys(slice[0]);
  const thead = `<tr>${keys.map(k => `<th>${escapeHtml(k)}</th>`).join('')}</tr>`;
  const tbody = slice.map(row =>
    `<tr>${keys.map(k => `<td>${escapeHtml(row[k] ?? '')}</td>`).join('')}</tr>`
  ).join('');
  return `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

function populateSelect(id, options, selected = null) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = options.map(o => {
    const safe = escapeHtml(o);
    return `<option value="${safe}" ${o === selected ? 'selected' : ''}>${safe}</option>`;
  }).join('');
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
  });
});

// ---------------------------------------------------------------------------
// ============================================================  CHARTS  ====
// ---------------------------------------------------------------------------

// Chart.js instance registry — destroy before re-creating to prevent leaks
const _charts = {};
function _destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

/**
 * Draw a doughnut chart using Chart.js.
 */
function drawPieChart(canvas, labels, values, palette) {
  const pal = palette || PALETTE;
  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) return;
  const id = canvas.id;
  _destroyChart(id);
  _charts[id] = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: pal.slice(0, values.length), borderWidth: 2, borderColor: '#fff' }],
    },
    options: {
      responsive: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.label}: ${ctx.parsed.toLocaleString()} (${(ctx.parsed / total * 100).toFixed(1)}%)`,
          },
        },
      },
    },
  });
}

/**
 * Draw a horizontal bar chart using Chart.js.
 */
function drawHBarChart(canvas, labels, values, opts = {}) {
  const pal = opts.palette || PALETTE;
  if (!labels.length) return;
  const id = canvas.id;
  _destroyChart(id);
  const fmt = v => v >= 1e6 ? `${(v/1e6).toFixed(1)}M` : v >= 1e3 ? `${(v/1e3).toFixed(1)}K` : Number.isInteger(v) ? v.toString() : v.toFixed(1);
  _charts[id] = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: labels.map((_, i) => pal[i % pal.length]),
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${fmt(ctx.parsed.x)}` } },
      },
      scales: {
        x: { grid: { color: '#f0f0f0' }, ticks: { callback: v => fmt(v), font: { size: 11 } } },
        y: { grid: { display: false }, ticks: { font: { size: 11 } } },
      },
    },
  });
}

/**
 * Draw a line / area chart using Chart.js.
 */
function drawLineChart(canvas, labels, values) {
  if (!labels.length || !values.length) return;
  const id = canvas.id;
  _destroyChart(id);
  const fmt = v => v >= 1e6 ? `${(v/1e6).toFixed(1)}M` : v >= 1e3 ? `${(v/1e3).toFixed(1)}K` : v.toFixed(0);
  _charts[id] = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: '#10b981',
        backgroundColor: 'rgba(16,185,129,0.12)',
        borderWidth: 2,
        pointRadius: labels.length > 60 ? 0 : 3,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      responsive: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#f0f0f0' }, ticks: { maxTicksLimit: 12, font: { size: 10 } } },
        y: { grid: { color: '#f0f0f0' }, ticks: { callback: v => fmt(v), font: { size: 11 } } },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// =====================================================  DASHBOARD LOGIC  ===
// ---------------------------------------------------------------------------

// Active hub filter for dashboard
let _dashHubFilter = '';

async function loadDashboard() {
  try {
    const summary = await apiFetch('/api/dashboard/summary');
    state.summary = summary;

    const noData = document.getElementById('noDataBanner');
    const content = document.getElementById('dashboardContent');

    if (!summary.has_data) {
      noData.style.display = 'block';
      content.style.display = 'none';
      document.getElementById('headerStatus').textContent = 'No data loaded';
      return;
    }

    noData.style.display = 'none';
    content.style.display = 'block';

    const isClaims = summary.detected_type === 'soc';
    document.getElementById('headerStatus').textContent =
      `${summary.row_count.toLocaleString()} rows · ${summary.col_count} cols · ${isClaims ? 'Claims format' : 'Generic'}`;

    const now = new Date();
    document.getElementById('dashSubtitle').textContent =
      `Last updated ${now.toLocaleDateString()} ${now.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;

    // Populate hub filter
    await populateHubFilter(summary);

    resizeAllCanvases();

    await Promise.allSettled([
      loadKpiCards(),
      renderCogsDistribution(),
      renderHubPerformance(),
      renderTopOperatorChart(),
      renderClaimsByPremise(),
      renderRecentClaims(),
    ]);
  } catch (e) {
    showToast(`Dashboard error: ${e.message}`, 'error');
  }
}

async function populateHubFilter(summary) {
  const sel = document.getElementById('filterHub');
  if (!sel) return;
  const cols = summary.columns || [];
  if (!cols.includes('hub')) return;
  try {
    const data = await apiFetch('/api/dashboard/distribution?column=hub&limit=50');
    sel.innerHTML = '<option value="">All Hubs</option>' +
      data.map(d => `<option value="${escapeHtml(d.label)}">${escapeHtml(d.label)} (${d.count.toLocaleString()})</option>`).join('');
    sel.value = _dashHubFilter;
  } catch (e) {
    console.warn('hub filter error', e);
  }
}

function applyDashboardFilter() {
  _dashHubFilter = document.getElementById('filterHub')?.value || '';
  const statusEl = document.getElementById('dashFilterStatus');
  if (statusEl) statusEl.textContent = _dashHubFilter ? `Filtered: ${_dashHubFilter}` : '';
  Promise.allSettled([
    loadKpiCards(),
    renderCogsDistribution(),
    renderHubPerformance(),
    renderTopOperatorChart(),
    renderClaimsByPremise(),
    renderRecentClaims(),
  ]);
}

const KPI_COLORS = ['kpi-card-green','kpi-card-blue','kpi-card-amber','kpi-card-purple','kpi-card-rose','kpi-card-teal'];

async function loadKpiCards() {
  try {
    const cards = await apiFetch('/api/dashboard/metrics');
    const grid = document.getElementById('kpiGrid');
    if (!grid) return;
    grid.innerHTML = cards.map((c, i) => `
      <div class="kpi-card ${KPI_COLORS[i % KPI_COLORS.length]}">
        <span class="kpi-icon">${escapeHtml(c.icon)}</span>
        <div class="kpi-value">${escapeHtml(c.value)}</div>
        <div class="kpi-label">${escapeHtml(c.label)}</div>
      </div>
    `).join('');
  } catch (e) {
    console.warn('kpi cards error', e);
  }
}

// Green palette for Claims dashboard charts
const GREEN_PALETTE = [
  '#10b981','#34d399','#6ee7b7','#a7f3d0','#d1fae5',
  '#059669','#047857','#065f46','#14b8a6','#2dd4bf',
  '#0ea5e9','#38bdf8','#7dd3fc','#93c5fd','#6366f1',
];

async function renderCogsDistribution() {
  const canvas = document.getElementById('cogsDistCanvas');
  const legend = document.getElementById('cogsDistLegend');
  if (!canvas) return;
  try {
    const data = await apiFetch('/api/dashboard/cogs-distribution');
    if (!data.length) { return; }
    const labels = data.map(d => d.label);
    const values = data.map(d => d.count);
    drawPieChart(canvas, labels, values, GREEN_PALETTE);
    if (legend) {
      legend.innerHTML = data.map((d, i) => `
        <span class="legend-item">
          <span class="legend-dot" style="background:${GREEN_PALETTE[i % GREEN_PALETTE.length]}"></span>
          ${escapeHtml(d.label)}: ${d.count.toLocaleString()} (${d.pct}%)
        </span>
      `).join('');
    }
  } catch (e) {
    console.warn('cogs distribution error', e);
  }
}

async function renderHubPerformance() {
  const canvas = document.getElementById('hubPerfCanvas');
  if (!canvas) return;
  try {
    const hubParam = _dashHubFilter ? `&hub=${encodeURIComponent(_dashHubFilter)}` : '';
    const data = await apiFetch(`/api/dashboard/hub-performance?limit=10${hubParam}`);
    if (!data.length) return;
    const labels = data.map(d => d.hub);
    const claimsVals = data.map(d => d.claims);
    drawHBarChart(canvas, labels, claimsVals, { palette: GREEN_PALETTE });
  } catch (e) {
    console.warn('hub performance error', e);
  }
}

async function renderTopOperatorChart() {
  const canvas = document.getElementById('topOpCanvas');
  const limit  = parseInt(document.getElementById('topOpLimit')?.value || '8', 10);
  if (!canvas || !state.summary?.columns?.includes('name')) return;
  try {
    const data = await apiFetch(
      `/api/dashboard/top-by?group_col=name&value_col=name&agg=count&limit=${limit}`
    );
    const labels = data.map(d => d.label);
    const values = data.map(d => d.value);
    drawHBarChart(canvas, labels, values, { palette: GREEN_PALETTE });
  } catch (e) {
    console.warn('top operator error', e);
  }
}

async function renderClaimsByPremise() {
  const canvas = document.getElementById('claimsPremiseCanvas');
  const limit  = parseInt(document.getElementById('topClaimLimit')?.value || '8', 10);
  if (!canvas || !state.summary?.columns?.includes('claims_name')) return;
  try {
    const col = encodeURIComponent('claims_name');
    const data = await apiFetch(
      `/api/dashboard/top-by?group_col=${col}&value_col=${col}&agg=count&limit=${limit}`
    );
    const labels = data.map(d => d.label);
    const values = data.map(d => d.value);
    drawHBarChart(canvas, labels, values, { palette: GREEN_PALETTE });
  } catch (e) {
    console.warn('claims by premise error', e);
  }
}

async function renderRecentClaims() {
  const el = document.getElementById('recentClaimsTable');
  const countEl = document.getElementById('recentClaimsCount');
  if (!el) return;
  try {
    const rows = await apiFetch('/api/dashboard/recent-claims?limit=20');
    if (!rows.length) { el.innerHTML = '<p class="muted">No data.</p>'; return; }

    const keys = Object.keys(rows[0]);
    const thead = `<tr>${keys.map(k => `<th>${escapeHtml(k)}</th>`).join('')}</tr>`;

    const tbody = rows.map(row => {
      const cogs = parseFloat(row['cogs_share_local']);
      return `<tr>${keys.map(k => {
        const val = row[k] ?? '';
        if (k === 'cogs_share_local' && !isNaN(cogs)) {
          const cls = cogs >= 0.8 ? 'cogs-high' : cogs >= 0.4 ? 'cogs-mid' : 'cogs-low';
          return `<td><span class="cogs-badge ${cls}">${escapeHtml(String(val))}</span></td>`;
        }
        return `<td title="${escapeHtml(String(val))}">${escapeHtml(String(val))}</td>`;
      }).join('')}</tr>`;
    }).join('');

    el.innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
    if (countEl) countEl.textContent = `${rows.length} records`;
  } catch (e) {
    console.warn('recent claims error', e);
  }
}

async function exportDashboard() {
  showToast('Exporting…', 'info');
  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: '', columns: [], page: 1, page_size: 100000 }),
    });
    if (!res.ok) throw new Error('Export failed');
    const data = await res.json();
    if (!data.rows.length) { showToast('No data to export.', 'error'); return; }
    const keys = Object.keys(data.rows[0]);
    const rows = [keys, ...data.rows.map(r => keys.map(k => r[k] ?? ''))];
    const result = await apiFetch('/api/export/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: 'claims_export', rows }),
    });
    showToast(`Saved to ${result.path}`, 'success');
  } catch (e) {
    showToast(`Export error: ${e.message}`, 'error');
  }
}

// Legacy stubs so existing references don't break
function populateDashboardControls() {}
async function renderDistChart() {}
async function renderTopByChart() {}
async function renderTimelineChart() {}
async function renderStatusTable() {}
async function loadMetricCards() { return loadKpiCards(); }

// ---------------------------------------------------------------------------
// =========================================================  UPLOAD  =======
// ---------------------------------------------------------------------------

async function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) await uploadFile(file);
}

function handleDrop(e) {
  e.preventDefault();
  document.getElementById('dropZone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
}

async function uploadFile(file) {
  const status = document.getElementById('uploadStatus');
  status.style.display = 'block';
  status.innerHTML = '<span class="spinner">&#9696;</span> Uploading and importing…';

  const form = new FormData();
  form.append('file', file);
  const appendMode = document.getElementById('appendMode')?.checked || false;
  form.append('append', appendMode ? 'true' : 'false');

  try {
    const result = await apiFetch('/api/upload', { method: 'POST', body: form });

    const mode = result.append_mode ? 'appended to' : 'replaced';
    status.innerHTML = `
      <div class="success-box">
        &#10003; <strong>${escapeHtml(result.filename)}</strong> ${mode} dataset:
        <strong>${result.row_count.toLocaleString()}</strong> rows added
        (total: <strong>${result.total_rows.toLocaleString()}</strong> rows)
      </div>`;

    // Show column preview
    const previewCard = document.getElementById('columnPreviewCard');
    previewCard.style.display = 'block';
    document.getElementById('columnPreview').innerHTML = buildTable(
      result.columns.map((c, i) => ({ '#': i + 1, 'Column Name': c }))
    );

    showToast(`Imported ${result.row_count.toLocaleString()} rows`, 'success');
    await loadImportHistory();
    await loadDashboard();
    await populateAllFormColumns();
    await loadSearchColumns();

  } catch (e) {
    status.innerHTML = `<div class="error-box">&#10007; ${escapeHtml(e.message)}</div>`;
    showToast(`Upload failed: ${e.message}`, 'error');
  }
}

async function loadImportHistory() {
  try {
    const rows = await apiFetch('/api/imports');
    const el = document.getElementById('importHistory');
    el.innerHTML = rows.length
      ? buildTable(rows.map(r => ({
          ID: r.import_id,
          File: r.filename,
          Type: r.file_type,
          Rows: r.row_count.toLocaleString(),
          Imported: (r.imported_at || '').slice(0, 19),
        })))
      : '<p class="muted">No imports yet.</p>';
  } catch (e) {
    console.warn('import history error', e);
  }
}

// ---------------------------------------------------------------------------
// ====================================================  FILE SPLIT  =========
// ---------------------------------------------------------------------------

let _splitFile = null;

function handleSplitFileSelect(e) {
  _splitFile = e.target.files[0];
  if (_splitFile) {
    document.getElementById('splitFileName').textContent = `Selected: ${_splitFile.name} (${(_splitFile.size / 1024 / 1024).toFixed(1)} MB)`;
    document.getElementById('splitStartBtn').disabled = false;
  }
}

function handleSplitDrop(e) {
  e.preventDefault();
  document.getElementById('splitDropZone').classList.remove('drag-over');
  _splitFile = e.dataTransfer.files[0];
  if (_splitFile) {
    document.getElementById('splitFileName').textContent = `Selected: ${_splitFile.name} (${(_splitFile.size / 1024 / 1024).toFixed(1)} MB)`;
    document.getElementById('splitStartBtn').disabled = false;
  }
}

async function startFileSplit() {
  if (!_splitFile) { showToast('Please select a file first.', 'error'); return; }

  const chunkSize = parseInt(document.getElementById('splitChunkSize').value, 10);
  const outputFolder = document.getElementById('splitOutputFolder').value.trim();

  if (!outputFolder) { showToast('Please specify an output folder.', 'error'); return; }

  const progressCard = document.getElementById('splitProgressCard');
  const bar = document.getElementById('splitProgressBar');
  const text = document.getElementById('splitProgressText');
  progressCard.style.display = 'block';
  bar.style.width = '0%';
  text.textContent = 'Uploading file...';
  document.getElementById('splitStartBtn').disabled = true;

  const form = new FormData();
  form.append('file', _splitFile);

  try {
    // Start the split (returns immediately, runs in background)
    await apiFetch(
      `/api/split/file?chunk_size=${chunkSize}&output_folder=${encodeURIComponent(outputFolder)}`,
      { method: 'POST', body: form }
    );

    text.textContent = 'Splitting in progress...';

    // Poll SSE progress
    const es = new EventSource('/api/split/file/progress');
    es.onmessage = ev => {
      const d = JSON.parse(ev.data);
      if (d.done && !d.error) {
        bar.style.width = '100%';
        text.textContent = `Done! ${d.files_written} XLSX files written to ${outputFolder}`;
        es.close();
        showToast(`Split complete: ${d.files_written} files`, 'success');
        document.getElementById('splitStartBtn').disabled = false;
        loadSplitHistory();
        return;
      }
      if (d.error) {
        text.textContent = `Error: ${d.error}`;
        es.close();
        showToast(`Split error: ${d.error}`, 'error');
        document.getElementById('splitStartBtn').disabled = false;
        return;
      }
      bar.style.width = `${d.progress}%`;
      text.textContent = `${d.progress}% — ${d.files_written} files written...`;
    };
    es.onerror = () => {
      es.close();
      document.getElementById('splitStartBtn').disabled = false;
    };

  } catch (e) {
    text.textContent = `Error: ${e.message}`;
    showToast(`Split error: ${e.message}`, 'error');
    document.getElementById('splitStartBtn').disabled = false;
  }
}

async function loadSplitHistory() {
  try {
    const rows = await apiFetch('/api/split/exports');
    const el = document.getElementById('splitHistory');
    el.innerHTML = rows.length
      ? buildTable(rows.map(r => ({
          ID: r.export_id,
          'Chunk Size': r.chunk_size,
          Files: r.file_count,
          'Export Folder': r.output_folder,
          'Exported At': (r.exported_at || '').slice(0, 19),
        })))
      : '<p class="muted">No exports yet.</p>';
  } catch (e) {
    console.warn('split history error', e);
  }
}

// ---------------------------------------------------------------------------
// ======================================================  AGGREGATE  =======
// ---------------------------------------------------------------------------

async function populateAggregateForm(summary) {
  const isSOC = summary.detected_type === 'soc';
  const allCols = summary.columns;
  const numCols = summary.numeric_cols;
  const dtCols  = summary.datetime_cols;
  const strCols = summary.string_cols;

  populateSelect('aggPersonKey', allCols,
    isSOC && allCols.includes(SOC_DEFAULTS.personKey) ? SOC_DEFAULTS.personKey : allCols[0]);

  // Numeric col checkboxes
  const numPicker = document.getElementById('numericColPicker');
  numPicker.innerHTML = numCols.map(c => {
    const checked = isSOC && SOC_DEFAULTS.numericCols.includes(c) ? 'checked' : '';
    const safe = escapeHtml(c);
    return `<label class="checkbox-item"><input type="checkbox" value="${safe}" ${checked}> ${safe}</label>`;
  }).join('');

  // Date col checkboxes
  const datePicker = document.getElementById('dateColPicker');
  datePicker.innerHTML = dtCols.map(c => {
    const checked = isSOC && SOC_DEFAULTS.dateCols.includes(c) ? 'checked' : '';
    const safe = escapeHtml(c);
    return `<label class="checkbox-item"><input type="checkbox" value="${safe}" ${checked}> ${safe}</label>`;
  }).join('');

  // Category col checkboxes
  const catPicker = document.getElementById('catColPicker');
  catPicker.innerHTML = strCols.map(c => {
    const checked = isSOC && SOC_DEFAULTS.catCols.includes(c) ? 'checked' : '';
    const safe = escapeHtml(c);
    return `<label class="checkbox-item"><input type="checkbox" value="${safe}" ${checked}> ${safe}</label>`;
  }).join('');
}

function getChecked(pickerId) {
  return [...document.querySelectorAll(`#${pickerId} input[type=checkbox]:checked`)].map(i => i.value);
}

async function runAggregate() {
  const personKey  = document.getElementById('aggPersonKey').value;
  const numericCols = getChecked('numericColPicker');
  const dateCols   = getChecked('dateColPicker');
  const catCols    = getChecked('catColPicker');

  const spinner = document.getElementById('aggSpinner');
  spinner.style.display = 'inline';

  try {
    const result = await apiFetch('/api/aggregate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ person_key: personKey, numeric_cols: numericCols, date_cols: dateCols, category_cols: catCols }),
    });

    state.aggCurrentPage = 1;
    document.getElementById('aggPreviewCard').style.display = 'block';
    showToast(`Aggregation complete: ${result.row_count?.toLocaleString() ?? '?'} persons`, 'success');
    await populateClusterForm();
    await loadAggPreview();
  } catch (e) {
    showToast(`Aggregation error: ${e.message}`, 'error');
  } finally {
    spinner.style.display = 'none';
  }
}

async function loadAggPreview() {
  try {
    const PAGE_SIZE = 50;
    const data = await apiFetch(`/api/aggregate/preview?page=${state.aggCurrentPage}&size=${PAGE_SIZE}`);
    document.getElementById('aggPreview').innerHTML = buildTable(data.rows || []);
    document.getElementById('aggPageInfo').textContent = `Page ${state.aggCurrentPage}`;
  } catch (e) {
    console.warn('agg preview error', e);
  }
}

function aggPage(delta) {
  state.aggCurrentPage = Math.max(1, state.aggCurrentPage + delta);
  loadAggPreview();
}

async function exportAgg() {
  showToast('Exporting…', 'info');
  try {
    const result = await apiFetch('/api/aggregate/export');
    showToast(`Saved to ${result.path}`, 'success');
  } catch (e) {
    showToast(`Export error: ${e.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// =========================================================  CLUSTER  ======
// ---------------------------------------------------------------------------

async function populateClusterForm() {
  const picker = document.getElementById('clusterFeaturePicker');
  try {
    const data = await apiFetch('/api/aggregate/columns');
    if (!data.available || !data.numeric_cols.length) {
      picker.innerHTML = '<p class="muted">Run aggregation first to enable clustering.</p>';
      return;
    }
    picker.innerHTML = data.numeric_cols.map(c => {
      // Auto-select _sum columns as sensible defaults
      const checked = c.endsWith('_sum') ? 'checked' : '';
      const safe = escapeHtml(c);
      return `<label class="checkbox-item"><input type="checkbox" value="${safe}" ${checked}> ${safe}</label>`;
    }).join('');
  } catch (e) {
    picker.innerHTML = '<p class="muted">Run aggregation first to enable clustering.</p>';
  }
}

async function runCluster() {
  const alg        = document.getElementById('clusterAlg').value;
  const n          = parseInt(document.getElementById('clusterN').value, 10);
  const featureCols = getChecked('clusterFeaturePicker');

  if (!featureCols.length) { showToast('Select at least one feature column.', 'error'); return; }

  const spinner = document.getElementById('clusterSpinner');
  spinner.style.display = 'inline';

  try {
    const result = await apiFetch('/api/cluster', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ algorithm: alg, n_clusters: n, feature_cols: featureCols }),
    });

    document.getElementById('clusterResultCard').style.display = 'block';

    // Draw bar chart of cluster distribution
    const dist = result.distribution || {};
    const clabels = Object.keys(dist).map(k => `Cluster ${k}`);
    const cvals   = Object.values(dist);
    const cCanvas = document.getElementById('clusterBarCanvas');
    drawHBarChart(cCanvas, clabels, cvals);

    // Distribution table
    document.getElementById('clusterDistTable').innerHTML = buildTable(
      Object.entries(dist).map(([k, v]) => ({ 'Cluster': k, 'Count': v.toLocaleString() }))
    );

    if (result.silhouette_score != null) {
      showToast(`Clustering done! Silhouette score: ${result.silhouette_score.toFixed(3)}`, 'success');
    } else {
      showToast('Clustering complete!', 'success');
    }

    state.clusterCurrentPage = 1;
    await loadClusterPreview();

  } catch (e) {
    showToast(`Clustering error: ${e.message}`, 'error');
  } finally {
    spinner.style.display = 'none';
  }
}

async function loadClusterPreview() {
  try {
    const PAGE_SIZE = 50;
    const data = await apiFetch(`/api/cluster/results?page=${state.clusterCurrentPage}&size=${PAGE_SIZE}`);
    document.getElementById('clusterPreview').innerHTML = buildTable(data.rows || []);
    document.getElementById('clusterPageInfo').textContent = `Page ${state.clusterCurrentPage}`;
  } catch (e) {
    console.warn('cluster preview error', e);
  }
}

function clusterPage(delta) {
  state.clusterCurrentPage = Math.max(1, state.clusterCurrentPage + delta);
  loadClusterPreview();
}

async function exportCluster() {
  showToast('Exporting…', 'info');
  try {
    const result = await apiFetch('/api/cluster/export');
    showToast(`Saved to ${result.path}`, 'success');
  } catch (e) {
    showToast(`Export error: ${e.message}`, 'error');
  }
}

async function loadClusterHistory() {
  try {
    const rows = await apiFetch('/api/cluster/history');
    const el = document.getElementById('clusterHistory');
    el.innerHTML = rows.length
      ? buildTable(rows.map(r => ({
          ID: r.run_id,
          Algorithm: r.algorithm,
          'N Clusters': r.n_clusters,
          'Features': (r.feature_columns || []).join(', '),
          'Silhouette': r.silhouette_score != null ? r.silhouette_score.toFixed(3) : '—',
          'Run At': (r.run_at || '').slice(0, 19),
        })))
      : '<p class="muted">No cluster runs yet.</p>';
  } catch (e) {
    console.warn('cluster history error', e);
  }
}

// ---------------------------------------------------------------------------
// =========================================================  SEARCH  ========
// ---------------------------------------------------------------------------

async function loadSearchColumns() {
  try {
    const data = await apiFetch('/api/search/columns');
    if (!data.columns.length) {
      document.getElementById('searchNoData').style.display = 'block';
      document.getElementById('searchResultsCard').style.display = 'none';
      return;
    }
    document.getElementById('searchNoData').style.display = 'none';

    const sel = document.getElementById('searchColumns');
    sel.innerHTML = '<option value="">All columns</option>' +
      data.columns.map(c => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join('');
  } catch (e) {
    console.warn('search columns error', e);
  }
}

async function runSearch() {
  state.searchCurrentPage = 1;
  await executeSearch();
}

async function executeSearch() {
  const query = document.getElementById('searchQuery').value.trim();
  const colSelect = document.getElementById('searchColumns');
  const selectedCols = [...colSelect.selectedOptions].map(o => o.value).filter(v => v);

  try {
    const result = await apiFetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        columns: selectedCols,
        page: state.searchCurrentPage,
        page_size: 50,
      }),
    });

    const card = document.getElementById('searchResultsCard');
    card.style.display = 'block';
    document.getElementById('searchNoData').style.display = 'none';

    document.getElementById('searchResultCount').textContent =
      `${result.total_rows.toLocaleString()} results${query ? ` for "${query}"` : ''}`;
    document.getElementById('searchResults').innerHTML = buildTable(result.rows || []);
    document.getElementById('searchPageInfo').textContent =
      `Page ${result.page} of ${result.total_pages}`;
  } catch (e) {
    showToast(`Search error: ${e.message}`, 'error');
  }
}

function searchPage(delta) {
  state.searchCurrentPage = Math.max(1, state.searchCurrentPage + delta);
  executeSearch();
}

async function exportSearchResults() {
  showToast('Exporting…', 'info');
  const query = document.getElementById('searchQuery').value.trim();
  const colSelect = document.getElementById('searchColumns');
  const selectedCols = [...colSelect.selectedOptions].map(o => o.value).filter(v => v);
  try {
    const data = await apiFetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, columns: selectedCols, page: 1, page_size: 100000 }),
    });
    if (!data.rows.length) { showToast('No results to export.', 'error'); return; }
    const keys = Object.keys(data.rows[0]);
    const rows = [keys, ...data.rows.map(r => keys.map(k => r[k] ?? ''))];
    const result = await apiFetch('/api/export/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: 'search_results', rows }),
    });
    showToast(`Saved to ${result.path}`, 'success');
  } catch (e) {
    showToast(`Export error: ${e.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// ================================================  POPULATE ALL FORMS  ====
// ---------------------------------------------------------------------------

async function populateAllFormColumns() {
  try {
    const summary = await apiFetch('/api/dashboard/summary');
    state.summary = summary;
    if (!summary.has_data) return;

    await populateAggregateForm(summary);
    await populateClusterForm();
    await loadSearchColumns();
  } catch (e) {
    console.warn('populate columns error', e);
  }
}

// ---------------------------------------------------------------------------
// ====================================================  INITIALIZATION  ====
// ---------------------------------------------------------------------------

async function init() {
  await loadImportHistory();
  await loadSplitHistory();
  await loadClusterHistory();
  await loadDashboard();
  await loadSearchColumns();

  // If data exists, also populate form columns
  if (state.summary?.has_data) {
    await populateAllFormColumns();
    await populateClusterForm();
  }
}

// Chart.js handles its own responsive sizing — just set explicit pixel dimensions
// for canvases that haven't been claimed by a Chart.js instance yet.
function resizeAllCanvases() {
  document.querySelectorAll('canvas.chart-canvas').forEach(c => {
    if (_charts[c.id]) return; // Chart.js manages this canvas
    const rect = c.parentElement.getBoundingClientRect();
    const w = rect.width > 50 ? Math.floor(rect.width - 40) : 560;
    c.width  = w;
    c.height = c.classList.contains('chart-canvas-wide') ? 220 : 260;
  });
}

window.addEventListener('resize', () => {
  Object.values(_charts).forEach(ch => ch.resize());
});

// ---------------------------------------------------------------------------
// =====================================================  UPDATE SYSTEM  =====
// ---------------------------------------------------------------------------

let _lastUpdateCheck = null;

async function loadVersionFooter() {
  try {
    const data = await apiFetch('/api/update/current-version');
    document.getElementById('versionText').textContent = `v${data.version}`;
  } catch (e) {
    document.getElementById('versionText').textContent = 'v?.?.?';
  }
}

async function silentUpdateCheck() {
  try {
    const data = await apiFetch('/api/update/check');
    _lastUpdateCheck = data;
    if (data.update_available) {
      document.getElementById('updateBannerText').textContent =
        `Update available: v${data.remote_version} — ${data.changelog.split('\n')[0] || 'New version ready'}`;
      document.getElementById('updateBanner').style.display = 'flex';
    }
  } catch (e) {
    console.warn('Silent update check failed:', e);
  }
}

function dismissUpdateBanner() {
  document.getElementById('updateBanner').style.display = 'none';
}

async function showUpdateModal() {
  const modal = document.getElementById('updateModal');
  modal.style.display = 'flex';
  const ids = ['updateModalLoading','updateModalNoConfig','updateModalError',
               'updateModalUpToDate','updateModalAvailable'];
  ids.forEach(id => { document.getElementById(id).style.display = 'none'; });
  document.getElementById('updateModalLoading').style.display = 'block';

  try {
    const data = await apiFetch('/api/update/check');
    _lastUpdateCheck = data;
    document.getElementById('updateModalLoading').style.display = 'none';

    if (data.error && data.error.includes('not configured')) {
      document.getElementById('updateModalNoConfig').style.display = 'block';
      return;
    }
    if (data.error) {
      document.getElementById('updateModalError').style.display = 'block';
      document.getElementById('updateModalErrorText').textContent = data.error;
      return;
    }
    if (!data.update_available) {
      document.getElementById('updateModalUpToDate').style.display = 'block';
      document.getElementById('updateCurrentVerText').textContent = data.current_version;
      return;
    }

    document.getElementById('updateModalAvailable').style.display = 'block';
    document.getElementById('updateModalCurVer').textContent = `v${data.current_version}`;
    document.getElementById('updateModalNewVer').textContent = `v${data.remote_version}`;
    document.getElementById('updateModalBuildDate').textContent = data.build_date
      ? `Build date: ${data.build_date}` : '';
    document.getElementById('updateModalMandatory').style.display =
      data.mandatory ? 'inline-block' : 'none';
    document.getElementById('updateModalChangelog').textContent =
      data.changelog || 'No changelog provided.';

    document.getElementById('updateDownloadBtn').style.display = 'inline-flex';
    document.getElementById('updateDownloadBtn').disabled = false;
    document.getElementById('updateInstallBtn').style.display = 'none';
    document.getElementById('updateDownloadSpinner').style.display = 'none';
    document.getElementById('updateDownloadStatus').textContent = '';
    document.getElementById('updateBanner').style.display = 'none';
  } catch (e) {
    document.getElementById('updateModalLoading').style.display = 'none';
    document.getElementById('updateModalError').style.display = 'block';
    document.getElementById('updateModalErrorText').textContent = e.message;
  }
}

function closeUpdateModal() {
  document.getElementById('updateModal').style.display = 'none';
}

async function downloadUpdate() {
  const btn = document.getElementById('updateDownloadBtn');
  const spinner = document.getElementById('updateDownloadSpinner');
  const status = document.getElementById('updateDownloadStatus');
  btn.disabled = true;
  spinner.style.display = 'inline-block';
  status.textContent = 'Downloading...';
  try {
    const data = await apiFetch('/api/update/download', { method: 'POST' });
    spinner.style.display = 'none';
    if (data.success) {
      status.textContent = 'Download complete. Ready to install.';
      btn.style.display = 'none';
      document.getElementById('updateInstallBtn').style.display = 'inline-flex';
      showToast('Update downloaded successfully.', 'success');
    } else {
      status.textContent = `Download failed: ${data.error}`;
      btn.disabled = false;
      showToast(`Download failed: ${data.error}`, 'error');
    }
  } catch (e) {
    spinner.style.display = 'none';
    status.textContent = `Error: ${e.message}`;
    btn.disabled = false;
    showToast(`Download error: ${e.message}`, 'error');
  }
}

async function installUpdate() {
  const btn = document.getElementById('updateInstallBtn');
  const status = document.getElementById('updateDownloadStatus');
  btn.disabled = true;
  status.textContent = 'Launching installer... The app will close shortly.';
  try {
    const data = await apiFetch('/api/update/install', { method: 'POST' });
    if (data.success) {
      status.textContent = data.message;
      showToast('Installer launched. Closing application...', 'info');
    } else {
      status.textContent = `Install failed: ${data.error}`;
      btn.disabled = false;
      showToast(`Install error: ${data.error}`, 'error');
    }
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
    btn.disabled = false;
    showToast(`Install error: ${e.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// =====================================================  SETTINGS MODAL  ====
// ---------------------------------------------------------------------------

async function clearData(scope) {
  const label = scope === 'all' ? 'Reset Everything' : 'Clear Imported Data';
  const detail = scope === 'all'
    ? 'This will wipe ALL tables including import history and cluster runs. Cannot be undone.'
    : 'This will remove raw_data and person_summary. Import history is kept. Cannot be undone.';
  if (!confirm(`${label}\n\n${detail}\n\nContinue?`)) return;

  try {
    const res = await apiFetch(`/api/data/clear?scope=${scope}`, { method: 'POST' });
    showToast(`Cleared: ${res.cleared.join(', ') || 'nothing to clear'}`, 'success');
    closeSettingsModal();
    await init();           // refresh dashboard + header status
  } catch (e) {
    showToast(`Failed to clear data: ${e.message}`, 'error');
  }
}

async function showSettingsModal() {
  document.getElementById('settingsModal').style.display = 'flex';
  try {
    const config = await apiFetch('/api/update/config');
    document.getElementById('settingsUpdateSource').value = config.update_source || '';
    document.getElementById('settingsCheckOnStartup').checked = config.check_on_startup;
    document.getElementById('settingsDownloadDir').value = config.download_dir || '';
  } catch (e) {
    console.warn('Failed to load settings:', e);
  }
}

function closeSettingsModal() {
  document.getElementById('settingsModal').style.display = 'none';
}

async function saveSettings() {
  const payload = {
    update_source: document.getElementById('settingsUpdateSource').value.trim(),
    check_on_startup: document.getElementById('settingsCheckOnStartup').checked,
    download_dir: document.getElementById('settingsDownloadDir').value.trim(),
  };
  try {
    await apiFetch('/api/update/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    showToast('Settings saved.', 'success');
    closeSettingsModal();
  } catch (e) {
    showToast(`Failed to save settings: ${e.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Run on page load
// ---------------------------------------------------------------------------
resizeAllCanvases();

async function prefillExportPaths() {
  try {
    const { path } = await apiFetch('/api/export/default-dir');
    const splitField = document.getElementById('splitOutputFolder');
    if (splitField && !splitField.value) splitField.value = path;
    const dlField = document.getElementById('settingsDownloadDir');
    if (dlField && !dlField.value) dlField.value = path;
  } catch (e) {
    // non-fatal
  }
}

async function fullInit() {
  loadVersionFooter();
  await init();
  prefillExportPaths();
  silentUpdateCheck();
}

fullInit().catch(console.error);
