/**
 * MACS+ Live Dashboard — Plotly charts + SSE listener
 *
 * Initializes 4 charts and updates them in real-time as runs complete.
 */

// ─── Chart initialization ──────────────────────────────────────────────────

const CHART_LAYOUT = {
    margin: { t: 40, r: 20, b: 50, l: 60 },
    showlegend: true,
    legend: { x: 0.01, y: 0.99, bgcolor: 'rgba(255,255,255,0.7)' },
    xaxis: { title: '', gridcolor: '#eee' },
    yaxis: { title: '', gridcolor: '#eee' },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
};

const PLOTLY_CONFIG = { responsive: true, displayModeBar: false };

function initCharts() {
    // Scatter: fireload vs glazing, colored pass/fail
    Plotly.newPlot('chart-scatter', [
        { x: [], y: [], mode: 'markers', name: 'Pass',
          marker: { color: 'steelblue', size: 6, opacity: 0.7 } },
        { x: [], y: [], mode: 'markers', name: 'Fail',
          marker: { color: 'coral', size: 6, opacity: 0.7 } },
    ], {
        ...CHART_LAYOUT,
        title: 'Fire Load vs Glazing Breakage',
        xaxis: { ...CHART_LAYOUT.xaxis, title: 'Fire Load (MJ/m²)' },
        yaxis: { ...CHART_LAYOUT.yaxis, title: 'Glazing Breakage (%)' },
    }, PLOTLY_CONFIG);

    // Capacity vs time
    Plotly.newPlot('chart-capacity', [
        // Traces added dynamically; trace 0 = average (added on first update)
    ], {
        ...CHART_LAYOUT,
        title: 'Total Capacity vs Time',
        xaxis: { ...CHART_LAYOUT.xaxis, title: 'Time (min)' },
        yaxis: { ...CHART_LAYOUT.yaxis, title: 'Capacity (kN/m)' },
    }, PLOTLY_CONFIG);

    // Beam temperature vs time
    Plotly.newPlot('chart-beam-temp', [], {
        ...CHART_LAYOUT,
        title: 'Beam Temperature vs Time',
        xaxis: { ...CHART_LAYOUT.xaxis, title: 'Time (min)' },
        yaxis: { ...CHART_LAYOUT.yaxis, title: 'Temperature (°C)' },
    }, PLOTLY_CONFIG);

    // Mesh temperature vs time
    Plotly.newPlot('chart-mesh-temp', [], {
        ...CHART_LAYOUT,
        title: 'Mesh Temperature vs Time',
        xaxis: { ...CHART_LAYOUT.xaxis, title: 'Time (min)' },
        yaxis: { ...CHART_LAYOUT.yaxis, title: 'Temperature (°C)' },
    }, PLOTLY_CONFIG);
}

// ─── SSE connection ────────────────────────────────────────────────────────

// Track data for averaging
const capacityData = [];    // [{times, values}]
const beamTempData = [];
const meshTempData = [];
let factoredHot = null;
let currentBatchId = null;

function formatTime(seconds) {
    if (!seconds && seconds !== 0) return '—';
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function updateProgress(progress) {
    if (!progress) return;
    document.getElementById('completed').textContent = progress.completed;
    document.getElementById('total').textContent = progress.total;
    document.getElementById('errors').textContent = progress.errors;
    document.getElementById('elapsed').textContent = formatTime(progress.elapsed_seconds);

    const pct = progress.total > 0 ? (progress.completed / progress.total * 100) : 0;
    document.getElementById('progress-bar').value = pct;
    document.getElementById('status-label').textContent =
        `Running... ${progress.completed}/${progress.total} (${Math.round(pct)}%)`;

    const stopBtn = document.getElementById('stop-batch-btn');
    if (stopBtn) {
        stopBtn.style.display = (progress.total > 0 && progress.completed < progress.total) ? 'inline-block' : 'none';
    }
}

function addRunToScatter(data) {
    const traceIndex = data.pass ? 0 : 1;
    if (data.qf != null && data.window_percent != null) {
        Plotly.extendTraces('chart-scatter', {
            x: [[data.qf]],
            y: [[data.window_percent]],
        }, [traceIndex]);
    }
}

function computeAverage(allData) {
    // Compute pointwise average across all runs
    if (allData.length === 0) return { times: [], values: [] };

    // Use the time grid from the first run (all runs share the same grid)
    const times = allData[0].times;
    const avgValues = times.map((_, i) => {
        let sum = 0, count = 0;
        for (const run of allData) {
            if (i < run.values.length) {
                sum += run.values[i];
                count++;
            }
        }
        return count > 0 ? sum / count : 0;
    });
    return { times, values: avgValues };
}

function addTimeSeriesTrace(chartId, allData, times, values, factoredLine) {
    const runTrace = {
        x: times, y: values,
        mode: 'lines',
        line: { color: 'lightsteelblue', width: 0.8 },
        showlegend: false,
    };

    allData.push({ times, values });

    // Recompute average
    const avg = computeAverage(allData);
    const avgTrace = {
        x: avg.times, y: avg.values,
        mode: 'lines',
        line: { color: 'coral', width: 2.5 },
        name: 'Average',
        showlegend: true,
    };

    // Rebuild traces: all individual runs + average + optional factored line
    const traces = allData.map(d => ({
        x: d.times, y: d.values,
        mode: 'lines',
        line: { color: 'lightsteelblue', width: 0.8 },
        showlegend: false,
    }));
    traces.push(avgTrace);

    if (factoredLine != null) {
        traces.push({
            x: [avg.times[0], avg.times[avg.times.length - 1]],
            y: [factoredLine, factoredLine],
            mode: 'lines',
            line: { color: 'red', width: 1.5, dash: 'dash' },
            name: `Factored load = ${factoredLine.toFixed(1)}`,
            showlegend: true,
        });
    }

    Plotly.react(chartId, traces,
        document.getElementById(chartId).layout, PLOTLY_CONFIG);
}

function handleRunComplete(data) {
    updateProgress(data.progress);
    addRunToScatter(data);

    if (data.time_series) {
        const ts = data.time_series;

        // Store factored_hot for capacity chart
        if (data.factored_hot != null && factoredHot == null) {
            factoredHot = data.factored_hot;
        }

        if (ts.total_plate_capacity) {
            addTimeSeriesTrace('chart-capacity', capacityData,
                ts.time_min, ts.total_plate_capacity, factoredHot);
        }
        if (ts.lofl_temp) {
            addTimeSeriesTrace('chart-beam-temp', beamTempData,
                ts.time_min, ts.lofl_temp, null);
        }
        if (ts.mesh_temp) {
            addTimeSeriesTrace('chart-mesh-temp', meshTempData,
                ts.time_min, ts.mesh_temp, null);
        }
    }
}

function handleBatchComplete(data) {
    const cancelled = data.status === 'cancelled';
    document.getElementById('status-label').textContent = cancelled ? 'Cancelled' : 'Batch Complete';
    document.getElementById('stop-batch-btn').style.display = 'none';
    document.getElementById('batch-summary').style.display = 'block';
    document.getElementById('summary-text').textContent = cancelled
        ? `Stopped after ${data.completed} runs (${data.errors} errors) in ${formatTime(data.elapsed_seconds)}.`
        : `Completed ${data.completed} runs with ${data.errors} errors in ${formatTime(data.elapsed_seconds)}.`;

    // Update DOCX download link with batch_id
    currentBatchId = data.batch_id || null;
    const docxBtn = document.getElementById('download-docx-btn');
    if (docxBtn && currentBatchId) {
        docxBtn.href = `/api/report/docx?batch_id=${encodeURIComponent(currentBatchId)}`;
    }
}

function connectSSE() {
    const evtSource = new EventSource('/api/events');

    evtSource.addEventListener('run_complete', (e) => {
        const data = JSON.parse(e.data);
        handleRunComplete(data);
    });

    evtSource.addEventListener('batch_complete', (e) => {
        const data = JSON.parse(e.data);
        handleBatchComplete(data);
    });

    evtSource.addEventListener('batch_error', (e) => {
        const data = JSON.parse(e.data);
        document.getElementById('status-label').textContent = `Error: ${data.error}`;
        document.getElementById('stop-batch-btn').style.display = 'none';
    });

    evtSource.onerror = () => {
        document.getElementById('status-label').textContent = 'Connection lost. Retrying...';
    };
}

// ─── Stop button ────────────────────────────────────────────────────────────
function setupStopButton() {
    document.getElementById('stop-batch-btn').addEventListener('click', () => {
        const btn = document.getElementById('stop-batch-btn');
        btn.disabled = true;
        btn.textContent = 'Stopping…';
        fetch('/api/batch/cancel', { method: 'POST' })
            .then((r) => r.json())
            .then(() => { btn.textContent = 'Stop'; btn.disabled = false; })
            .catch(() => { btn.textContent = 'Stop'; btn.disabled = false; });
    });
}

// ─── Initialize ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    setupStopButton();
    connectSSE();
});
