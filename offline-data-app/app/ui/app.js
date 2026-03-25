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

// SOC-specific column suggestions
const SOC_DEFAULTS = {
  personKey:    'operator',
  numericCols:  ['cogs_local', 'cogs_share_local', 'station_activity_total_ops', 'agency_ops_count'],
  dateCols:     ['lost_status_time'],
  catCols:      ['lost_status', 'station_reference', 'activity_type', 'type_of_lost'],
  orderCol:     'tracking_number',
  distCol1:     'type_of_lost',
  distCol2:     'activity_type',
  topGroupCol1: 'station_reference',
  topValCol1:   'cogs_local',
  topGroupCol2: 'operator',
  topValCol2:   'tracking_number',
  timelineDate: 'lost_status_time',
  statusCol:    'lost_status',
  clusterFeats: ['cogs_local', 'cogs_share_local', 'station_activity_total_ops', 'agency_ops_count'],
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

/**
 * Draw a pie / donut chart on a Canvas element.
 * @param {HTMLCanvasElement} canvas
 * @param {string[]} labels
 * @param {number[]} values
 */
function drawPieChart(canvas, labels, values) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) return;

  const cx = W / 2;
  const cy = H / 2;
  const r = Math.min(cx, cy) - 10;
  const inner = r * 0.5; // donut hole

  let start = -Math.PI / 2;
  values.forEach((v, i) => {
    const slice = (v / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start + slice);
    ctx.closePath();
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();
    start += slice;
  });

  // Donut hole
  ctx.beginPath();
  ctx.arc(cx, cy, inner, 0, 2 * Math.PI);
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--bg-card') || '#fff';
  ctx.fill();
}

/**
 * Draw a horizontal bar chart on a Canvas element.
 * @param {HTMLCanvasElement} canvas
 * @param {string[]} labels
 * @param {number[]} values
 * @param {object} opts — {title, formatValue}
 */
function drawHBarChart(canvas, labels, values, opts = {}) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  if (!labels.length) return;

  const pad = { top: 10, right: 20, bottom: 10, left: 4 };
  const labelMaxLen = Math.min(220, Math.max(...labels.map(l => l.length)) * 7 + 16);
  const barAreaX = pad.left + labelMaxLen;
  const barAreaW = W - barAreaX - pad.right;
  const rowH = Math.max(22, Math.floor((H - pad.top - pad.bottom) / labels.length));
  const barH = Math.min(rowH - 6, 22);
  const maxVal = Math.max(...values, 1);

  const fmt = opts.formatValue || (v => v >= 1e6 ? `${(v/1e6).toFixed(1)}M` : v >= 1e3 ? `${(v/1e3).toFixed(1)}K` : Number.isInteger(v) ? v.toString() : v.toFixed(1));

  ctx.font = '12px system-ui, sans-serif';
  ctx.fillStyle = '#333';

  labels.forEach((lbl, i) => {
    const y = pad.top + i * rowH;
    const barW = (values[i] / maxVal) * barAreaW;

    // Label (truncated)
    const maxChars = Math.floor(labelMaxLen / 7);
    const displayLbl = lbl.length > maxChars ? lbl.slice(0, maxChars - 1) + '…' : lbl;
    ctx.fillStyle = '#555';
    ctx.textAlign = 'right';
    ctx.fillText(displayLbl, pad.left + labelMaxLen - 6, y + barH / 2 + 4);

    // Bar
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    ctx.beginPath();
    ctx.roundRect
      ? ctx.roundRect(barAreaX, y, barW, barH, 3)
      : ctx.rect(barAreaX, y, barW, barH);
    ctx.fill();

    // Value label
    ctx.fillStyle = '#333';
    ctx.textAlign = 'left';
    ctx.fillText(fmt(values[i]), barAreaX + barW + 4, y + barH / 2 + 4);
  });
}

/**
 * Draw a line chart on a Canvas element.
 * @param {HTMLCanvasElement} canvas
 * @param {string[]} labels
 * @param {number[]} values
 */
function drawLineChart(canvas, labels, values) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  if (!labels.length || !values.length) return;

  const pad = { top: 20, right: 20, bottom: 40, left: 60 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const maxV = Math.max(...values, 1);
  const minV = 0;
  const range = maxV - minV || 1;

  const xStep = plotW / Math.max(labels.length - 1, 1);

  // Grid lines (5)
  ctx.strokeStyle = '#e5e7eb';
  ctx.lineWidth = 1;
  for (let g = 0; g <= 5; g++) {
    const gy = pad.top + plotH - (g / 5) * plotH;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(pad.left + plotW, gy);
    ctx.stroke();
    ctx.fillStyle = '#999';
    ctx.font = '11px system-ui';
    ctx.textAlign = 'right';
    const gv = minV + (g / 5) * range;
    ctx.fillText(gv >= 1e3 ? `${(gv/1e3).toFixed(0)}K` : gv.toFixed(0), pad.left - 6, gy + 4);
  }

  // X-axis labels (show at most 12)
  const step = Math.max(1, Math.floor(labels.length / 12));
  ctx.fillStyle = '#666';
  ctx.font = '10px system-ui';
  ctx.textAlign = 'center';
  labels.forEach((lbl, i) => {
    if (i % step !== 0 && i !== labels.length - 1) return;
    const x = pad.left + i * xStep;
    ctx.fillText(lbl.slice(0, 10), x, pad.top + plotH + 16);
  });

  // Area fill
  const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
  gradient.addColorStop(0, 'rgba(78,121,167,0.3)');
  gradient.addColorStop(1, 'rgba(78,121,167,0.02)');
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = pad.left + i * xStep;
    const y = pad.top + plotH - ((v - minV) / range) * plotH;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.lineTo(pad.left + (values.length - 1) * xStep, pad.top + plotH);
  ctx.lineTo(pad.left, pad.top + plotH);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.strokeStyle = '#4e79a7';
  ctx.lineWidth = 2;
  values.forEach((v, i) => {
    const x = pad.left + i * xStep;
    const y = pad.top + plotH - ((v - minV) / range) * plotH;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Dots
  ctx.fillStyle = '#4e79a7';
  values.forEach((v, i) => {
    if (labels.length > 60 && i % step !== 0) return;
    const x = pad.left + i * xStep;
    const y = pad.top + plotH - ((v - minV) / range) * plotH;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, 2 * Math.PI);
    ctx.fill();
  });
}

// ---------------------------------------------------------------------------
// =====================================================  DASHBOARD LOGIC  ===
// ---------------------------------------------------------------------------

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

    document.getElementById('headerStatus').textContent =
      `${summary.row_count.toLocaleString()} rows · ${summary.col_count} columns · ${summary.detected_type === 'soc' ? 'SOC format detected' : 'Generic format'}`;

    await loadMetricCards();
    populateDashboardControls(summary);

    // Render charts with defaults
    await Promise.allSettled([
      renderDistChart('distCol1', 'distCanvas1', 'distLegend1'),
      renderDistChart('distCol2', 'distCanvas2', 'distLegend2'),
      renderTopByChart('topGroupCol1', 'topValCol1', 'topAgg1', 'topCanvas1'),
      renderTopByChart('topGroupCol2', 'topValCol2', 'topAgg2', 'topCanvas2'),
      renderTimelineChart(),
      renderStatusTable(),
    ]);
  } catch (e) {
    showToast(`Dashboard error: ${e.message}`, 'error');
  }
}

async function loadMetricCards() {
  try {
    const cards = await apiFetch('/api/dashboard/metrics');
    const el = document.getElementById('metricCards');
    el.innerHTML = cards.map(c => `
      <div class="metric-card">
        <div class="metric-icon">${escapeHtml(c.icon)}</div>
        <div class="metric-value">${escapeHtml(c.value)}</div>
        <div class="metric-label">${escapeHtml(c.label)}</div>
      </div>
    `).join('');
  } catch (e) {
    console.warn('metric cards error', e);
  }
}

function populateDashboardControls(summary) {
  const strCols = summary.string_cols;
  const numCols = summary.numeric_cols;
  const dtCols  = summary.datetime_cols;
  const allCols = summary.columns;

  const isSOC = summary.detected_type === 'soc';

  // Distribution col pickers
  populateSelect('distCol1', strCols, isSOC && strCols.includes(SOC_DEFAULTS.distCol1) ? SOC_DEFAULTS.distCol1 : strCols[0]);
  populateSelect('distCol2', strCols, isSOC && strCols.includes(SOC_DEFAULTS.distCol2) ? SOC_DEFAULTS.distCol2 : strCols[1] || strCols[0]);

  // Top-by col pickers
  populateSelect('topGroupCol1', strCols, isSOC && strCols.includes(SOC_DEFAULTS.topGroupCol1) ? SOC_DEFAULTS.topGroupCol1 : strCols[0]);
  populateSelect('topValCol1',   numCols, isSOC && numCols.includes(SOC_DEFAULTS.topValCol1)   ? SOC_DEFAULTS.topValCol1   : numCols[0]);
  populateSelect('topGroupCol2', strCols, isSOC && strCols.includes(SOC_DEFAULTS.topGroupCol2) ? SOC_DEFAULTS.topGroupCol2 : strCols[0]);
  populateSelect('topValCol2',   allCols, isSOC && allCols.includes(SOC_DEFAULTS.topValCol2)   ? SOC_DEFAULTS.topValCol2   : allCols[0]);

  // Timeline date col
  const dateOptions = [...dtCols, ...strCols.filter(c => c.includes('date') || c.includes('time') || c.includes('at'))];
  populateSelect('timelineDateCol', dateOptions.length ? dateOptions : allCols,
    isSOC && dtCols.includes(SOC_DEFAULTS.timelineDate) ? SOC_DEFAULTS.timelineDate : (dateOptions[0] || allCols[0]));

  // Status distribution col
  populateSelect('statusDistCol', strCols, isSOC && strCols.includes(SOC_DEFAULTS.statusCol) ? SOC_DEFAULTS.statusCol : strCols[0]);
}

async function renderDistChart(selectId, canvasId, legendId) {
  const col = document.getElementById(selectId)?.value;
  if (!col) return;
  try {
    const data = await apiFetch(`/api/dashboard/distribution?column=${encodeURIComponent(col)}&limit=10`);
    const canvas = document.getElementById(canvasId);
    const legend = document.getElementById(legendId);
    if (!canvas) return;

    const labels = data.map(d => d.label);
    const values = data.map(d => d.count);
    drawPieChart(canvas, labels, values);

    if (legend) {
      legend.innerHTML = data.map((d, i) => `
        <span class="legend-item">
          <span class="legend-dot" style="background:${PALETTE[i % PALETTE.length]}"></span>
          ${escapeHtml(d.label)} (${escapeHtml(d.pct)}%)
        </span>
      `).join('');
    }
  } catch (e) {
    console.warn('dist chart error', e);
  }
}

async function renderTopByChart(groupSelId, valSelId, aggSelId, canvasId) {
  const groupCol = document.getElementById(groupSelId)?.value;
  const valCol   = document.getElementById(valSelId)?.value;
  const agg      = document.getElementById(aggSelId)?.value || 'sum';
  if (!groupCol || !valCol) return;

  try {
    const data = await apiFetch(
      `/api/dashboard/top-by?group_col=${encodeURIComponent(groupCol)}&value_col=${encodeURIComponent(valCol)}&agg=${agg}&limit=10`
    );
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const labels = data.map(d => d.label);
    const values = data.map(d => d.value);
    drawHBarChart(canvas, labels, values);
  } catch (e) {
    console.warn('top-by chart error', e);
  }
}

async function renderTimelineChart() {
  const dateCol     = document.getElementById('timelineDateCol')?.value;
  const granularity = document.getElementById('timelineGranularity')?.value || 'month';
  if (!dateCol) return;

  try {
    const data = await apiFetch(
      `/api/dashboard/timeline?date_col=${encodeURIComponent(dateCol)}&agg=count&granularity=${granularity}`
    );
    const canvas = document.getElementById('timelineCanvas');
    if (!canvas) return;

    const labels = data.map(d => d.date);
    const values = data.map(d => d.value);
    drawLineChart(canvas, labels, values);
  } catch (e) {
    console.warn('timeline chart error', e);
  }
}

async function renderStatusTable() {
  const col   = document.getElementById('statusDistCol')?.value;
  const limit = document.getElementById('statusDistLimit')?.value || 20;
  if (!col) return;

  try {
    const data = await apiFetch(
      `/api/dashboard/distribution?column=${encodeURIComponent(col)}&limit=${limit}`
    );
    const el = document.getElementById('statusDistTable');
    if (!el) return;

    if (!data.length) { el.innerHTML = '<p class="muted">No data.</p>'; return; }

    const rows = data.map((d, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${escapeHtml(d.label)}</td>
        <td>${escapeHtml(d.count.toLocaleString())}</td>
        <td>
          <div style="display:flex;align-items:center;gap:.5rem">
            <div style="width:${Math.round(d.pct * 2)}px;height:10px;background:${PALETTE[i % PALETTE.length]};border-radius:3px"></div>
            ${escapeHtml(d.pct)}%
          </div>
        </td>
      </tr>
    `).join('');

    el.innerHTML = `<table>
      <thead><tr><th>#</th><th>Value</th><th>Count</th><th>Share</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  } catch (e) {
    console.warn('status table error', e);
  }
}

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
  try {
    const res = await fetch('/api/aggregate/export');
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    triggerDownload(blob, 'person_summary.csv');
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
  try {
    const res = await fetch('/api/cluster/export');
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    triggerDownload(blob, 'clustered_persons.csv');
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
  showToast('Exporting current search results...', 'info');
  // Fetch a large page of results
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
        page: 1,
        page_size: 100000,
      }),
    });

    if (!result.rows.length) { showToast('No results to export.', 'error'); return; }

    const keys = Object.keys(result.rows[0]);
    const csv = [keys.join(','), ...result.rows.map(r => keys.map(k => {
      const v = String(r[k] ?? '');
      return v.includes(',') || v.includes('"') || v.includes('\n') ? `"${v.replace(/"/g, '""')}"` : v;
    }).join(','))].join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    triggerDownload(blob, `search_results.csv`);
    showToast('Export complete.', 'success');
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

// Size all canvas elements to match their CSS display size
function resizeAllCanvases() {
  document.querySelectorAll('canvas.chart-canvas').forEach(c => {
    const rect = c.parentElement.getBoundingClientRect();
    const w = rect.width > 50 ? Math.floor(rect.width - 40) : 560;
    c.width  = w;
    c.height = c.classList.contains('chart-canvas-wide') ? 220 : 260;
  });
}

window.addEventListener('resize', () => { resizeAllCanvases(); });

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

async function fullInit() {
  loadVersionFooter();
  await init();
  silentUpdateCheck();
}

fullInit().catch(console.error);
