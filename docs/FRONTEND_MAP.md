# FRONTEND_MAP.md — Pravah Stream + Static single-file pages

> **Status note:** this document was written as the blueprint for splitting two single-file HTML
> pages into shared CSS + ES modules; that split has since landed (`rtsp/static/js/shared/`,
> `rtsp/static/js/stream/`, `rtsp/static/js/static_mode/`, both templates now just
> `<script type="module" src="...">`). Most of the analysis below describes the **pre-split**
> monolithic templates and their original line numbers, which no longer exist as such — it is kept
> as historical design rationale for the module boundaries actually shipped. The pipeline-upload
> related rows have been corrected to current (post-removal) reality; other line-number references
> are otherwise untouched.

Blueprint for a **behaviour-preserving** split of two single-file HTML pages into shared CSS +
ES modules. Two source files:

| Page | File | Total lines | CSS | Markup | JS `<script>` |
|------|------|------------:|-----|--------|---------------|
| **STREAM** | `templates/index_stream.html` | 2596 | 8–740 | 741–1216 | 1217–2594 |
| **STATIC** | `templates/index_static.html` | 2653 | 8–740 | 741–1099 | 1100–2651 |

Both `<head>`s are byte-identical for the first 8 lines, including `<title>Pravah · Stream Mode</title>`
(STATIC's title is **wrong/copy-pasted** — it should say Static Mode; see §7) and
`<link rel="stylesheet" href="/static/assets/colors_and_type.css">` (external design tokens — untouched by this refactor).

> Line numbers below are **absolute file lines**. Where a JS function is cited, both the STREAM
> line and STATIC line are given as `S:1234 / T:1234`.

---

## 1. CSS COMPARISON

**The two `<style>` blocks (lines 8–740) are BYTE-IDENTICAL.** Verified with `diff` on the extracted
ranges — zero differences. 733 lines, ~120 rules, covering: reset, ambient particles, header, progress
bar, step system, buttons, water-card, mode tiles, probe badge, duration tiles, GCP table, sensor panel,
input-unit-wrap, dashboard (topbar/warn/progress/metric/charts/feed/overlay/save-bar), canvas-step layouts
(frame-container / side-panel / GCP form+list / AOI bars), inline-schematic.

- **Rules only in STREAM:** none.
- **Rules only in STATIC:** none.
- **Rules present in both but different:** none.

### Dead CSS caveat (important for the "optional per-page css" decision)
Although the blocks are identical, a large share of the CSS is **used only by STREAM's markup**. STATIC's
markup (741–1099) contains no dashboard, so these selectors match nothing in STATIC:
`.dash-topbar, .dash-breadcrumb, .dash-badges, .status-badge(.recording/.processing/.idle), .dash-select,
.warn-banner, .dash-progress-row, .prog-col/.prog-track/.prog-fill/.prog-indeterminate/.prog-time,
.last-result-pill, .site-info, .metric-row/.metric-card/.m-*, .charts-col/.chart-card/.chart-*/.chart-canvas,
.feed-card/.feed-header/#feedCanvas/.feed-legend, .session-overlay*, .save-status-bar/.save-chip*, #step6
scrollbar rules, .duration-tiles/.duration-tile, .gcp-table*, .mode-tile.tile-static` variants (STATIC has
the static tile but not the dashboard). STATIC **does** still use: reset, particles, header, progress bar,
step system, buttons, water-card, mode-tiles, sensor panel, input-unit-wrap, frame-container, side-panel,
GCP form/list, AOI bars, `.save-chip` (reused for the video-upload chip), `#step6` (re-purposed as a plain
water-card results view).

### Recommendation
Ship **one shared `css/app.css`** containing the entire identical block. Do **not** create
`stream.css` / `static_mode.css` — there is no divergence to justify a split, and dead selectors are
harmless (no runtime cost, no specificity conflicts). Splitting would create a maintenance hazard (two
copies of `.btn` to keep in sync) for zero behavioural gain. The bytes **must stay identical** to preserve
appearance; keep every class name and the two inline `data:image/svg+xml` select-arrow URLs verbatim.

---

## 2. JS FUNCTION INVENTORY

Notation: **R** = globals read, **W** = globals written, **DOM** = element ids touched, **API** = endpoints.
"globals" = the module-level `let/const` listed in §4. `document`/`window`/`fetch` etc. omitted from R/W.

### 2A. STREAM — `index_stream.html` (script 1217–2594)

**Top-level state (1221–1231):** `API`, `currentStep`, `selectedDurationS`, `gcpRowCount`(unused),
`pollTimer`, `tickTimer`, `sessionConfig`, `lastStatus`, `recordingStartedAt`, `chartViewStart`, `CHART_WINDOW`.
**Nav constants (1236–1242):** `STEP_LABELS`, `STEP_PROGRESS` (both unused), `PROG_MAP`, `LABEL_MAP`.
**Canvas state (1293–1305):** `snapshotImg`, `videoWidth`, `videoHeight`, `videoLoaded`, `frameCaptured`,
`livePreviewActive`, `gcps`, `pendingGcp`, `editingGcpIndex`, `originGcpIndex`, `aoiCorners`, `draggingAoi`,
`aoiDashOffset`, `streamPipeline` (**singular, File|null**), `GCP_COLORS`.
**Other module vars:** `_step2RecTimer`(1791), `snapshotPollTimer`(2355), `warnTimer`(2536).

| Function | Lines | Purpose | Reads | Writes | DOM ids | API |
|---|---|---|---|---|---|---|
| `showStep(n)` | 1244–1280 | Switch active `.step`, update progress fill/pill; start/stop live preview on 4a; refit AOI on 4c; refresh Ha on 4b | currentStep, frameCaptured, livePreviewActive, videoLoaded, PROG_MAP, LABEL_MAP | currentStep | step{n}, progressFill, stepPill, stepInfo, frameCanvas4c, frameContainer4c | — |
| `syncDuration()` | 1285–1288 | Clamp batch-duration input → `selectedDurationS` | — | selectedDurationS | durationInput | — |
| `startLivePreview()` | 1310–1334 | Point `#livePreview` img at MJPEG live endpoint; auto-retry on error | frameCaptured | livePreviewActive | rtspUrl, livePreview, frameEmpty4a | `/api/stream/live?rtsp_url=` |
| `stopLivePreview()` | 1336–1341 | Clear live img src to close HTTP stream | — | livePreviewActive | livePreview | — |
| `captureFrame()` | 1343–1373 | Fetch a still snapshot, load into `snapshotImg`, draw to 4a/4c canvases, reveal GCP section | — | snapshotImg, videoWidth/Height, videoLoaded, frameCaptured | rtspUrl, captureBtn, frameCanvas4a, overlayCanvas4a, captureSection, gcpSection (+4c) | `/api/stream/snapshot?rtsp_url=` |
| `recaptureFrame()` | 1375–1400 | Reset capture; clear gcps/aoi/origin; revert to live preview | — | videoLoaded, frameCaptured, gcps, aoiCorners, originGcpIndex | gcpSection, captureSection, captureBtn, frameCanvas4a/4c, overlayCanvas4a | — |
| `drawSnapshotToCanvas(canvas,container)` | 1402–1408 | Blit `snapshotImg` to a canvas, then size it | snapshotImg, videoWidth/Height | — | (args) | — |
| `sizeCanvasToContainer(canvas,container)` | 1413–1423 | Letterbox-fit canvas into container (INSET 18) | videoWidth/Height | — | (args) | — |
| `fitOverlay(frameCanvas,container)` | 1425–1438 | Position overlay canvas over frame canvas | videoWidth/Height | — | `.overlay-canvas` | — |
| `getPixelCoords(e,canvas)` | 1440–1447 | Map mouse event → {dispX,dispY,pixelX,pixelY} | — | — | (args) | — |
| `installFrameResizeObserver(containerId,canvasId)` | 1449–1464 | ResizeObserver → re-size + redraw GCP/AOI overlays | videoLoaded | — | (args), triggers redrawGcp/AoiOverlay | — |
| **DOMContentLoaded handler** | 1469–1545 | Wire resize observers, waterZ/camXYZ inputs, overlay click (GCP add), gcpSave/gcpCancel, AOI mousedown/move/up, keydown-delete | videoLoaded, gcps, pendingGcp, editingGcpIndex, aoiCorners, draggingAoi, currentStep | pendingGcp, editingGcpIndex, gcps, aoiCorners, draggingAoi | overlayCanvas4a/4c, gcpForm, gcpFormTitle/Pixel, gcpX/Y/Z, gcpSaveBtn, gcpCancelBtn | — |
| `setOrigin(i)` | 1547–1551 | Toggle origin GCP | originGcpIndex | originGcpIndex | — | — |
| `updateGcpUI()` | 1553–1584 | Re-render GCP list + counter; enable Next; wire per-row edit/origin/remove | gcps, originGcpIndex, editingGcpIndex | editingGcpIndex | gcpCounter, gcpNext, gcpList, gcpForm, gcpFormTitle/Pixel, gcpX/Y/Z | — |
| `removeGcp(i)` | 1586 | Splice a GCP, redraw | gcps | gcps | — | — |
| `redrawGcpOverlay()` | 1588–1598 | Clear + redraw all GCP markers on overlay4a | gcps, pendingGcp, originGcpIndex, GCP_COLORS | — | overlayCanvas4a | — |
| `drawMarker(ctx,…)` | 1600–1624 | Draw one numbered GCP marker (+origin ring/label) | — | — | — | — |
| `roundRect(ctx,…)` | 1626–1631 | Rounded-rect path helper | — | — | — | — |
| `updateAoiUI()` | 1636–1644 | Update AOI readout count, enable Next, set instruction text | aoiCorners | — | aoiReadoutN, aoiReadout, aoiNext, aoiInstruction | — |
| `updateAoiReadout()` | 1646–1648 | Set AOI corner count label | aoiCorners | — | aoiReadoutN | — |
| `redrawAoiOverlay()` | 1650–1687 | Draw AOI polygon + corner handles | aoiCorners, aoiDashOffset | — | overlayCanvas4c | — |
| `animateAoi()` (IIFE) | 1689–1693 | rAF loop marching the AOI dash offset | aoiCorners | aoiDashOffset | — | — |
| `onPipelineUpload(input)` | — | **REMOVED.** Pipeline upload no longer exists; the Pipeline bar shows a fixed `quasi-v2 (Bodart 2024)` tag with no upload control. | — | — | — | — |
| `removePipeline()` | — | **REMOVED** with `onPipelineUpload` above. | — | — | — | — |
| `_inToM(inches)` | 1716 | inches→metres (0.0254), 6dp | — | — | — | — |
| `updateHaDisplay()` | 1718–1722 | Show water-surface elevation in m | — | — | waterZ, haFallbackDisplay | — |
| `buildStreamConfig()` | 1724–1749 | Build PIV config JSON (gcps src/dst, z_0/h_ref, lens_position, h_a, aoi_corners), origin-shifted | videoWidth/Height, gcps, originGcpIndex, aoiCorners | — | camX/Y/Z, waterZ | — |
| `testRtsp()` | 1754–1781 | Probe RTSP; on ok enable Next + reveal Record-batch | — | — | rtspUrl, probeBadge, probeBtn, step2Next, recordBatchBtn | `/api/stream/probe?rtsp_url=` |
| **`#rtspUrl` keydown listener** | 1784–1786 | Enter → testRtsp | — | — | rtspUrl | — |
| `step2StartRecording()` | 1793–1824 | **Dead** (no `step2RecStartBtn` in markup) start raw recording + timer | — | _step2RecTimer | rtspUrl, step2RecStartBtn/StopBtn/Indicator | `/api/stream/record/start` |
| `step2StopRecording()` | 1826–1843 | **Dead** stop raw recording | — | _step2RecTimer | step2RecStartBtn/StopBtn/Indicator | `/api/stream/record/stop` |
| `toggleSensor()` | 1848–1854 | Toggle sensor panel open + aria | — | — | sensorToggle, sensorPanel | — |
| `onProtocolChange()` | 1855–1859 | Show RTU vs TCP sensor rows | — | — | sProtocol, sRtuRow, sTcpRow | — |
| `testSensor()` | 1860–1882 | POST sensor cfg, show measured m | — | — | sensorTestStatus | `/api/sensor/test` |
| `buildSensorConfig()` | 1883–1902 | Assemble modbus config object | — | — | sProtocol, sSlaveId, sAddress, sRegType, sScale, sUnit, sComPort/sBaud/sParity or sTcpHost/sTcpPort | — |
| `startStream()` | 1909–1946 | POST multipart start (rtsp, duration, config, sensor, pipeline); go to dashboard; begin polling | selectedDurationS, streamPipeline | sessionConfig | rtspUrl, sensorToggle, dashDuration, rtspLabel | `/api/stream/start` |
| `stopStream()` | 1948–1953 | Confirm + POST stop | — | — | — | `/api/stream/stop` |
| `patchDuration()` | 1955–1963 | PATCH batch duration from dashboard select | — | — | dashDuration | `/api/stream/config` |
| `startPolling()` | 1968–1973 | Start 2s status poll + 1s tick | pollTimer, tickTimer | pollTimer, tickTimer | — | — |
| `pollStatus()` | 1975–2001 | Poll status; fan out to all dashboard updaters; stop on end | — | lastStatus, recordingStartedAt, pollTimer, tickTimer | — | `/api/stream/status` |
| `updateRecordingUI(data)` | 2006–2027 | Show/hide manual rec buttons + elapsed | — | — | recStartBtn, recStopBtn, recIndicator | — |
| `startRecording()` | 2029–2041 | Manual record start | — | — | recStartBtn | `/api/stream/record/start` |
| `stopRecording()` | 2043–2062 | Manual record stop, show saved file | — | — | recStopBtn, recIndicator | `/api/stream/record/stop` |
| `updateBadges(data)` | 2067–2100 | Recording/processing badges + cooldown countdown | — | — | recBadge, procBadge, procAnim, procLabel, recBatchNum | — |
| `updateProgressRow(data)` | 2105–2112 | Last-result pill text | — | — | lastResultPill | — |
| `tickProgress()` | 2114–2125 | Advance recording progress bar/time each second | recordingStartedAt, lastStatus | — | recProgress, recTimeLabel | — |
| `updateMetricCards(results)` | 2130–2138 | Fill mean/median/max metric cards | — | — | (via setMetric) | — |
| `setMetric(valId,deltaId,val,prevVal)` | 2140–2153 | Set one metric value + delta | — | — | (args) | — |
| `panChart/2/3(dir)` | 2158–2160 | Pan a chart window | chartViewStart | chartViewStart | — | — |
| `updateCharts(results)` | 2162–2165 | → redrawCharts | — | — | — | — |
| `redrawCharts(results)` | 2167–2173 | Draw 3 line charts | lastStatus | — | chartMean/Median/Max | — |
| `drawLineChart(canvasId,results,getter,color,panIdx)` | 2175–2270 | Canvas-2D sparkline w/ window+pan | chartViewStart, CHART_WINDOW | — | (arg canvasId) | — |
| `drawFeedCanvas(data)` | 2275–2350 | Draw feed bg/grid/AOI/GCP/placeholder | sessionConfig | — | feedCanvas, feedBatchNum | — |
| `recordBatch()` | 2357–2396 | Trigger snapshot batch record + poll | selectedDurationS | snapshotPollTimer | rtspUrl, recordBatchBtn, snapshotStatusWrap, snapshotChip | `/api/stream/record_snapshot` |
| `pollSnapshotStatus()` | 2398–2453 | Poll snapshot record status → chip | — | snapshotPollTimer | snapshotChip, recordBatchBtn | `/api/stream/snapshot_status` |
| `saveExtraBatch()` | 2458–2473 | Queue an extra desktop save | — | — | saveExtraBtn | `/api/stream/save_batch` |
| `updateSaveStatus(data)` | 2475–2531 | Render save-status bar/chip/button | — | — | saveStatusBar, extraSaveChip, saveExtraBtn | — |
| `showWarn(msg)` | 2537–2543 | Show auto-dismissing warning banner | warnTimer | warnTimer | warnBanner, warnText | — |
| `dismissWarn()` | 2544–2546 | Hide warning banner | — | — | warnBanner | — |
| `showSessionEndOverlay(data)` | 2551–2570 | Build + append session-end overlay | — | — | (creates `.session-overlay`) | — |
| **Init: sensor-config fetch** | 2576–2590 | Load saved sensor cfg into form | — | — | sProtocol, sComPort, sBaud, sParity, sTcpHost, sTcpPort, sSlaveId, sAddress, sScale, sUnit | `/api/sensor/config` |
| **Init: resize listener** | 2593 | Redraw charts on window resize | lastStatus | — | — | — |

### 2B. STATIC — `index_static.html` (script 1100–2651)

Same module-var block as STREAM **except**: `streamPipelines` no longer exists (pipeline upload was
removed) and **`staticVideoFile = null`** (1186) is added.

Functions **identical to STREAM** (byte-for-byte, see §3): `showStep`\*, `syncDuration`, `startLivePreview`,
`stopLivePreview`, `captureFrame`, `recaptureFrame`, `drawSnapshotToCanvas`, `sizeCanvasToContainer`,
`fitOverlay`, `getPixelCoords`, `installFrameResizeObserver`, `setOrigin`, `updateGcpUI`, `removeGcp`,
`redrawGcpOverlay`, `drawMarker`, `roundRect`, `updateAoiUI`, `updateAoiReadout`, `redrawAoiOverlay`,
`animateAoi`, `_inToM`, `updateHaDisplay`, `buildStreamConfig`, `testRtsp`, `step2StartRecording`,
`step2StopRecording`, `toggleSensor`, `onProtocolChange`, `testSensor`, `buildSensorConfig`, `patchDuration`,
`startPolling`, `pollStatus`, `updateRecordingUI`, `startRecording`, `stopRecording`, `updateBadges`,
`updateProgressRow`, `tickProgress`, `updateMetricCards`, `setMetric`, `panChart/2/3`, `updateCharts`,
`redrawCharts`, `drawLineChart`, `drawFeedCanvas`, `recordBatch`, `pollSnapshotStatus`, `saveExtraBatch`,
`updateSaveStatus`, `showWarn`, `dismissWarn`, `showSessionEndOverlay`, sensor-config init fetch, resize init.
(\* `showStep` and the DOMContentLoaded body **differ slightly** — see §3.)

STATIC-only / divergent functions:

| Function | Lines | Purpose | Reads | Writes | DOM ids | API |
|---|---|---|---|---|---|---|
| `showStep(n)` (DIVERGENT) | 1127–1161 | Same as STREAM but on 4a calls `showStaticFrameStep()` instead of `startLivePreview()`; no `livePreviewActive` stop branch | currentStep, videoLoaded, PROG_MAP, LABEL_MAP | currentStep | step{n}, progressFill, stepPill, stepInfo, frameCanvas4c, frameContainer4c | — |
| `handleVideoUpload(input)` | 1298–1335 | Upload video, POST for first frame (server-side decode), load into `snapshotImg`, enable Next | — | staticVideoFile, videoLoaded, frameCaptured, snapshotImg, videoWidth/Height | videoFileInput, videoStatusWrap, videoChip, step2Next | `/api/static/first_frame` |
| `showStaticFrameStep()` | 1337–1349 | Draw uploaded first frame to 4a/4c, reveal GCP section | snapshotImg, videoLoaded | — | frameEmpty4a, frameCanvas4a/4c, overlayCanvas4a, captureSection, gcpSection | — |
| `onPipelineUpload(input)` (DIVERGENT) | — | **REMOVED.** No pipeline upload in current code. | — | — | — | — |
| `removePipelineAt(idx)` | — | **REMOVED** with `onPipelineUpload` above. | — | — | — | — |
| `renderPipelineTags()` | — | **REMOVED.** The Pipeline bar is now a static `quasi-v2 (Bodart 2024)` tag rendered directly in the template markup, not by JS. | — | — | — | — |
| `escapeHtml(s)` | — | Still exists, but now lives in `static_mode/results.js` (used only by `createResultCard`, not by any pipeline tag renderer, which is gone). | — | — | — | — |
| **DOMContentLoaded** (DIVERGENT) | 1410–1489 | Same wiring as STREAM **plus** final line `showStep(2)` (auto-advance past mode-select) | (same) | (same) | (same) | — |
| `startStream()` (DIVERGENT — same NAME, different job) | — | Does **one run** of quasi-v2 on the uploaded video and renders **one** result card — no pipeline queue (the sequential-multi-pipeline behaviour described below no longer applies) | staticVideoFile | sessionConfig | resultsContainer, staticStatus | `/api/process` (single call) |
| `pollJobUntilDone(cardIndex,jobId)` | 1928–1945 | Promise: poll one job's status to done/error, stream log | — | — | cardLog-{i} | `/api/status/{jobId}` |
| `setStaticStatus(msg)` | 1947–1950 | Set the top-of-results status line | — | — | staticStatus | — |
| `createResultCard(index,name)` | 1952–1976 | Build a per-pipeline result card (metrics + images + log) | — | — | resultsContainer, card-{i}, cardStatus-{i}, cardMean/Median/Max-{i}, cardImage/Overlay-{i}, cardLog-{i} | — |
| `metricBox(label,valueId)` | 1978–1982 | HTML string for one metric box | — | — | — | — |
| `setCardStatus(index,state,msg)` | 1984–1990 | Colour + text a card's status | — | — | cardStatus-{i} | — |
| `renderCardResults(index,data)` | 1992–2003 | Fill card metrics + result/overlay images | — | — | cardMean/Median/Max-{i}, cardImage/Overlay-{i} | — |
| `stopStream()` (DIVERGENT) | 2005–2010 | Same body as STREAM but **dead** — no caller in STATIC markup | — | — | — | `/api/stream/stop` |

**Dead in STATIC** (defined but no markup wires them, all dashboard-era): `patchDuration`, `startPolling`,
`pollStatus`, `updateRecordingUI`, `startRecording`, `stopRecording`, `updateBadges`, `updateProgressRow`,
`tickProgress`, `updateMetricCards`, `setMetric`, `panChart/2/3`, `updateCharts`, `redrawCharts`,
`drawLineChart`, `drawFeedCanvas`, `recordBatch`, `pollSnapshotStatus`, `saveExtraBatch`, `updateSaveStatus`,
`showWarn`, `dismissWarn`, `showSessionEndOverlay`, `testRtsp` + its `#rtspUrl` keydown listener,
`startLivePreview`, `stopLivePreview`, `captureFrame`, `recaptureFrame`, `step2Start/StopRecording`,
`stopStream`. These reference ids absent from STATIC (`rtspUrl`, `recBadge`, `feedCanvas`, `chartMean`,
`dashDuration`, …) and are guarded by null checks or never invoked; confirmed by grep that **none** of those
ids exist in `index_static.html`. The `#rtspUrl` keydown listener at STATIC 1753–1755 **will throw** at load
because `document.getElementById('rtspUrl')` is `null` — see §7.

---

## 3. SHARED CLASSIFICATION

**SHARED-IDENTICAL** (same name, byte-identical body in both pages — 54 items). Verified by aligned reads;
these are the extraction workers' safe-to-hoist set:
`syncDuration, startLivePreview, stopLivePreview, captureFrame, recaptureFrame, drawSnapshotToCanvas,
sizeCanvasToContainer, fitOverlay, getPixelCoords, installFrameResizeObserver, setOrigin, updateGcpUI,
removeGcp, redrawGcpOverlay, drawMarker, roundRect, updateAoiUI, updateAoiReadout, redrawAoiOverlay,
animateAoi (IIFE), _inToM, updateHaDisplay, buildStreamConfig, testRtsp, step2StartRecording,
step2StopRecording, toggleSensor, onProtocolChange, testSensor, buildSensorConfig, patchDuration,
startPolling, pollStatus, updateRecordingUI, startRecording, stopRecording, updateBadges, updateProgressRow,
tickProgress, updateMetricCards, setMetric, panChart, panChart2, panChart3, updateCharts, redrawCharts,
drawLineChart, drawFeedCanvas, recordBatch, pollSnapshotStatus, saveExtraBatch, updateSaveStatus, showWarn,
dismissWarn, showSessionEndOverlay`. Also identical: the entire state block (`API`…`CHART_WINDOW`),
`STEP_LABELS/STEP_PROGRESS/PROG_MAP/LABEL_MAP`, `GCP_COLORS`, `_step2RecTimer/snapshotPollTimer/warnTimer`,
the `#rtspUrl` keydown listener source, and the sensor-config + resize init blocks.

> Note: many "identical" functions are **live in STREAM, dead in STATIC** (see §2B dead list). They are
> still identical *source*, so a shared module is correct; STATIC just never calls them.

**SHARED-DIVERGENT** (same name, different body — describe precisely):
- **`showStep(n)`** — STREAM (1244–1280) has a live-preview branch: on `'4a'` `if(!frameCaptured) startLivePreview()`,
  `else if(livePreviewActive) stopLivePreview()`. STATIC (1127–1161) replaces that whole branch with
  `if(n==='4a') showStaticFrameStep();` and has **no** live-preview/`livePreviewActive` logic. Everything
  else (progress fill, pill, 4b Ha refresh, 4c AOI refit, scrollTo) is identical.
- **DOMContentLoaded handler** — STATIC appends one extra final statement `showStep(2);` (1488) that STREAM
  lacks. All listener wiring above it is identical.
- **`onPipelineUpload(input)`** — **REMOVED from both pages.** The pipeline-upload feature (and
  `streamPipeline`/`streamPipelines` state) no longer exists; the Pipeline bar in both templates is
  now a fixed `quasi-v2 (Bodart 2024)` tag with no upload control.
- **`startStream()`** — **Same name, still fundamentally different behaviour.** STREAM: POST
  `/api/stream/start` multipart, then `showStep(6)`, `drawFeedCanvas()`, `startPolling()` — enters
  the live dashboard. STATIC: validates `staticVideoFile`, `showStep(6)`, then a single POST to
  `/api/process` and a poll of `/api/status/{job_id}` to completion, rendering **one** result card
  (the multi-pipeline queue described in older revisions of this doc no longer exists). **These
  must NOT be merged into one shared function** — split by page.
- **`stopStream()`** — bodies identical, but STATIC's is dead (no caller). Classify as shared source,
  stream-only usage.

**STREAM-ONLY functions:** none pipeline-related any more (`onPipelineUpload`/`removePipeline` removed).
All the dashboard functions are technically shared *source* but **stream-only in usage**.

**STATIC-ONLY functions:** `handleVideoUpload`, `showStaticFrameStep`, `escapeHtml` (now in
`static_mode/results.js`), `pollJobUntilDone`, `setStaticStatus`, `createResultCard`, `metricBox`,
`setCardStatus`, `renderCardResults`, and the `startStream` static variant. (`onPipelineUpload`,
`removePipelineAt`, `renderPipelineTags` removed.)

---

## 4. GLOBAL MUTABLE STATE (#1 ES-module integration risk)

Every mutable global is currently a bare top-level `let`, so **any function in the same file can read/write
it directly**. Under ES modules a plain `import { x }` binding is read-only for the importer — writes must go
through the owning module (setter fn) or a shared mutable-object namespace. Enumerated with owner module
(from §6) and read/write sites:

| Global | Type | Written by | Read by | Notes / per-page |
|---|---|---|---|---|
| `currentStep` | number/str | `showStep` | `showStep`, keydown-delete listener (4c guard) | both |
| `selectedDurationS` | number | `syncDuration` | `startStream`(stream), `recordBatch` | both |
| `sessionConfig` | object | `startStream` (both) | `drawFeedCanvas` (stream) | both; STATIC sets it but nothing reads it |
| `lastStatus` | object | `pollStatus` | `tickProgress`, `redrawCharts`, resize listener | stream-live only |
| `recordingStartedAt` | number | `pollStatus` | `tickProgress` | stream-live only |
| `pollTimer`,`tickTimer` | interval id | `startPolling`,`pollStatus` | `startPolling`,`pollStatus` | stream-live only |
| `chartViewStart` | number[3] | `panChart/2/3` | `drawLineChart` | stream-live only |
| `snapshotImg` | Image | `captureFrame`(stream), `handleVideoUpload`(static) | `drawSnapshotToCanvas`, `showStaticFrameStep` | both — set by different fns |
| `videoWidth`,`videoHeight`,`videoLoaded`,`frameCaptured` | num/bool | `captureFrame`/`handleVideoUpload`, `recaptureFrame`, `showStep` observers | sizing, overlays, `buildStreamConfig`, `installFrameResizeObserver` | both — heavily shared |
| `livePreviewActive` | bool | `startLivePreview`,`stopLivePreview`,`showStep` | `showStep` | stream only (STATIC never sets true) |
| `gcps` | array | overlay-click listener, gcpSave, `removeGcp`, `recaptureFrame` | `updateGcpUI`, `redrawGcpOverlay`, `buildStreamConfig` | both |
| `pendingGcp` | object|null | overlay-click, gcpSave, gcpCancel | `redrawGcpOverlay`, gcpSave | both |
| `editingGcpIndex` | number | overlay-click, gcpSave, gcpCancel, `updateGcpUI` | gcpSave | both |
| `originGcpIndex` | number | `setOrigin`, `recaptureFrame` | `updateGcpUI`, `redrawGcpOverlay`, `buildStreamConfig` | both |
| `aoiCorners` | array | AOI mousedown/move listeners, keydown-delete, `recaptureFrame` | `updateAoiUI`, `redrawAoiOverlay`, `buildStreamConfig`, `animateAoi`, `showStep` | both |
| `draggingAoi` | number | AOI mousedown/mouseup/move | AOI mousemove | both |
| `aoiDashOffset` | number | `animateAoi`, `redrawAoiOverlay`(reads) | `redrawAoiOverlay` | both |
| `streamPipeline` (STREAM) | — | **REMOVED** — pipeline upload no longer exists. | — | — |
| `streamPipelines` (STATIC) | — | **REMOVED** — pipeline upload no longer exists. | — | — |
| `staticVideoFile` (STATIC) | File|null | `handleVideoUpload` | `startStream`(static) | **static only** |
| `_step2RecTimer`,`snapshotPollTimer`,`warnTimer` | timer id | their record/poll/warn fns | same | both (snapshot/warn live in stream) |
| `gcpRowCount` | number | — | — | **unused in both** (safe to drop, but keep for byte-parity if paranoid) |

**Integration guidance:** the canvas/GCP/AOI cluster (`snapshotImg`, video*, `gcps`, `pendingGcp`,
`editingGcpIndex`, `originGcpIndex`, `aoiCorners`, `draggingAoi`, `aoiDashOffset`) is read/written across
~15 functions and both pages. Put it in **one shared mutable state module** exporting a single object
(e.g. `export const canvasState = {…}`) rather than individual `let`s, so cross-module writes work. Same for
the dashboard cluster (`lastStatus`, `recordingStartedAt`, timers, `chartViewStart`). Pipeline state
(`streamPipeline` scalar vs `streamPipelines` array) no longer exists — pipeline upload was removed
and there is nothing to keep or share for it.

---

## 5. INLINE EVENT HANDLERS (must be re-wired for ES modules)

Under `<script type="module">`, functions are **not** global — every inline `on*=` below breaks unless the
function is re-exposed (`window.fn = fn`) or replaced with `addEventListener`. Counts are exact.

> **Pipeline upload note:** `onPipelineUpload`, `removePipeline`, `removePipelineAt` are all
> **removed** from current code — every mention of them below is historical (pre-removal) and no
> longer wired to anything; the counts and `window.*` exposure lists were not recomputed post-removal.

### STREAM markup — 43 inline-handler occurrences, referencing these distinct functions:
`window.location.href` (786, native — no rewire), `showStep` (796, 846, 850, 928, 929, 1039, 1043, 1080),
`syncDuration` (826), `testRtsp` (830), `recordBatch` (834), `captureFrame` (890), `recaptureFrame` (902),
`updateHaDisplay` (951, 955, 959, 969), `toggleSensor` (982), `onProtocolChange` (990), `testSensor` (1027),
`this.style…` (1072 ×2, native — no rewire), `onPipelineUpload` (1074), `startStream` (1084),
`patchDuration` (1106), `startRecording` (1112), `stopRecording` (1113), `stopStream` (1115),
`dismissWarn` (1121), `saveExtraBatch` (1143), `panChart` (1175 ×2), `panChart2` (1182 ×2), `panChart3` (1189 ×2).
Plus **two generated-at-runtime** handlers inside `updateGcpUI` template strings — `setOrigin(${i})` (1569)
and `removeGcp(${i})` (1570) — and one in `onPipelineUpload` — `removePipeline()` (1703) — and
`location.reload()` in the session overlay (2567, native). 
**Distinct app functions needing `window.` exposure (STREAM): 19** —
`showStep, syncDuration, testRtsp, recordBatch, captureFrame, recaptureFrame, updateHaDisplay, toggleSensor,
onProtocolChange, testSensor, onPipelineUpload, startStream, patchDuration, startRecording, stopRecording,
stopStream, dismissWarn, saveExtraBatch, panChart, panChart2, panChart3, setOrigin, removeGcp, removePipeline`
(24 counting the three chart pans and the two runtime-generated ones separately).

### STATIC markup — 26 inline-handler occurrences:
`window.location.href` (786, native), `showStep` (796, 829, 833, 911, 912, 1022, 1026, 1063),
`handleVideoUpload` (822), `captureFrame` (873), `recaptureFrame` (885), `updateHaDisplay` (934, 938, 942, 952),
`toggleSensor` (965), `onProtocolChange` (973), `testSensor` (1010), `this.style…` (1055 ×2, native),
`onPipelineUpload` (1057), `startStream` (1067), `location.reload()` (1094 & 2624, native).
Plus runtime-generated: `setOrigin(${i})` (1513), `removeGcp(${i})` (1514), `removePipelineAt(' + i + ')` (1671).
**Distinct app functions needing `window.` exposure (STATIC): 12** —
`showStep, handleVideoUpload, captureFrame, recaptureFrame, updateHaDisplay, toggleSensor, onProtocolChange,
testSensor, onPipelineUpload, startStream, setOrigin, removeGcp, removePipelineAt`.

**Recommendation:** convert the static markup handlers (`showStep`, GCP list buttons, AOI, etc.) to
`addEventListener` where the element is static, but the **runtime-generated** buttons (`setOrigin`,
`removeGcp`, `removePipelineAt`/`removePipeline`) are built via `innerHTML` template strings — either keep a
small `window.*` shim for those exact names, or refactor `updateGcpUI`/`renderPipelineTags` to build nodes
+ `addEventListener`. Keeping `mode-tile onclick="window.location…"` and the two `this.style` hover handlers
as-is is fine (no app-fn dependency).

---

## 6. RECOMMENDED MODULE SPLIT

Root: `D:\pravah\claude-test\rtsp\static\`. **Hard constraint for all modules: DOM ids, CSS class names, and
`/api/...` paths must stay byte-identical** to what the tables above list — the backend and CSS depend on them.

```
static/
  css/
    app.css                     ← the entire identical <style> block (§1). No per-page css.
  js/
    shared/
      state.js                  ← canvas+dashboard mutable state as exported objects
      dom.js                    ← tiny $ = id=>document.getElementById helper (optional)
      api.js                    ← thin fetch wrappers for every /api endpoint used by BOTH pages
      canvas.js                 ← sizing/overlay/coords: sizeCanvasToContainer, fitOverlay,
                                   getPixelCoords, installFrameResizeObserver, drawSnapshotToCanvas,
                                   roundRect, drawMarker
      gcp.js                    ← setOrigin, updateGcpUI, removeGcp, redrawGcpOverlay + GCP_COLORS
      aoi.js                    ← updateAoiUI, updateAoiReadout, redrawAoiOverlay, animateAoi IIFE
      sensor.js                 ← toggleSensor, onProtocolChange, testSensor, buildSensorConfig,
                                   sensor-config init fetch
      config.js                 ← _inToM, updateHaDisplay, buildStreamConfig
      wizard.js                 ← PROG_MAP, LABEL_MAP + a base showStep() taking a per-page hook
    stream/
      preview.js                ← startLivePreview, stopLivePreview, captureFrame, recaptureFrame
      probe.js                  ← testRtsp (+#rtspUrl keydown), recordBatch, pollSnapshotStatus,
                                   step2Start/StopRecording, snapshotPollTimer/_step2RecTimer
      (no pipeline.js — pipeline upload removed; shipped code has no such module)
      dashboard.js              ← startPolling, pollStatus, updateBadges, updateRecordingUI,
                                   startRecording, stopRecording, updateProgressRow, tickProgress,
                                   updateMetricCards, setMetric, updateSaveStatus, saveExtraBatch,
                                   showWarn, dismissWarn, showSessionEndOverlay, patchDuration
      charts.js                 ← chartViewStart, CHART_WINDOW, panChart/2/3, updateCharts,
                                   redrawCharts, drawLineChart, resize listener
      feed.js                   ← drawFeedCanvas
      main.js                   ← stream startStream, stopStream, showStep hook (live preview),
                                   DOMContentLoaded wiring, window.* exposure
    static_mode/
      upload.js                 ← staticVideoFile, handleVideoUpload, showStaticFrameStep
      (no pipeline.js — pipeline upload removed; shipped code has no such module)
      results.js                ← startStream(static, single run/single result card), pollJobUntilDone,
                                   setStaticStatus, createResultCard, metricBox, setCardStatus,
                                   renderCardResults, escapeHtml (moved here, no longer tag-related)
      main.js                   ← stopStream(dead—may omit), showStep hook (showStaticFrameStep),
                                   DOMContentLoaded wiring + showStep(2), window.* exposure
```

Confirmed against the shipped tree (`rtsp/static/js/shared|stream|static_mode/*`): matches the above
exactly except that neither `stream/` nor `static_mode/` has a `pipeline.js`, and `static_mode/preview.js`
also exists (captureFrame/recaptureFrame, mirroring `stream/preview.js`).

**Per-module ownership / exports / imports:**

- **`shared/state.js`** — owns all cross-cutting mutable state. Export `canvasState` (snapshotImg,
  videoWidth, videoHeight, videoLoaded, frameCaptured, livePreviewActive, gcps, pendingGcp, editingGcpIndex,
  originGcpIndex, aoiCorners, draggingAoi, aoiDashOffset) and `appState` (currentStep, selectedDurationS,
  sessionConfig, lastStatus, recordingStartedAt, pollTimer, tickTimer). Imports: nothing.
- **`shared/api.js`** — exports functions wrapping `/api/stream/{live,snapshot,probe,start,stop,status,config,
  record/start,record/stop,record_snapshot,snapshot_status,save_batch}`, `/api/sensor/{test,config}`,
  `/api/static/first_frame`, `/api/process`, `/api/status/{id}`. Keep `API=''` (same-origin) constant here.
- **`shared/canvas.js`** — imports `canvasState`. Exports the sizing/overlay/draw helpers. `drawMarker`+
  `roundRect` used by `gcp.js`; `drawSnapshotToCanvas` used by preview/upload/wizard.
- **`shared/gcp.js`** — imports `canvasState`, `canvas.js` (drawMarker), `dom`. Exports `updateGcpUI,
  redrawGcpOverlay, setOrigin, removeGcp, GCP_COLORS`. Must expose `setOrigin`/`removeGcp` on `window`
  (runtime-generated onclicks).
- **`shared/aoi.js`** — imports `canvasState`, `canvas.js`. Exports AOI fns; `animateAoi` self-starts.
- **`shared/sensor.js`** — imports `api.js`, `dom`. Exposes `toggleSensor,onProtocolChange,testSensor` on
  window. Runs the sensor-config init fetch on import.
- **`shared/config.js`** — imports `canvasState`. Exports `_inToM, updateHaDisplay, buildStreamConfig`.
  Expose `updateHaDisplay` on window.
- **`shared/wizard.js`** — exports `PROG_MAP, LABEL_MAP` and a `makeShowStep(onEnter)` factory; each page's
  `main.js` supplies the divergent `'4a'` hook. Expose the resulting `showStep` on window.
- **`stream/*`** import from `shared/*`; `stream/main.js` composes them, defines the live `startStream`,
  and does the `window.*` assignments for all 24 handler names in §5.
- **`static_mode/*`** import from `shared/*`; `static_mode/main.js` defines the single-run `startStream`
  (not sequential — pipeline upload/queueing is gone), auto-calls `showStep(2)` after wiring, and exposes
  its handler names. It omits the dashboard imports (charts/feed/dashboard) entirely — they are dead in
  static — which also drops the `#rtspUrl` keydown crash (§7).

This yields **8 shared modules** and **5 stream / 4 static** page modules (no `pipeline.js` on either
side), grouped by concern (api / state / canvas / GCP / AOI / sensor / config / wizard; stream: preview,
probe, dashboard, charts, feed, main; static: upload, preview, results, main).

---

## 7. RISKS & ODDITIES (what will bite the extraction workers)

1. **STATIC ships the entire live-dashboard JS as dead code.** ~25 functions + the charts/feed/badge/save
   machinery are defined in `index_static.html` but reference ids that **do not exist** in its markup
   (grep-confirmed: no `rtspUrl, recBadge, feedCanvas, chartMean, dashDuration, warnBanner`, etc.). They are
   invoked only from the dashboard poll loop, which STATIC never starts. Workers should **not** port these
   into the static bundle — but must confirm nothing subtly depends on them first (nothing does).

2. **`#rtspUrl` keydown listener throws at load in STATIC.** Line 1753–1755 runs
   `document.getElementById('rtspUrl').addEventListener(...)` at top level; STATIC has no `#rtspUrl`, so this
   is a `TypeError` at parse-eval time. In the current single-file page it aborts the *rest of that inline
   script region after that point*? No — it's mid-script, so **everything defined after line ~1755 in STATIC
   currently fails to run** unless the browser hoisted them. **Check carefully:** function *declarations*
   (`function foo(){}`) are hoisted, so they exist, but the top-level statements after the throw
   (the sensor-config `fetch`, the resize listener, and crucially the `DOMContentLoaded` registration at
   1410 which is *before* the throw, so it survives) — verify execution order. Net effect today: STATIC likely
   logs an uncaught error but still works because the DOMContentLoaded handler (which calls `showStep(2)`) is
   registered *before* line 1755. **When modularising, simply don't include the stream probe module in
   static — the bug disappears.** Flag this as a latent pre-existing defect.

3. **`startStream()` is the same name for two completely different jobs** (live-dashboard vs a single
   `/api/process` call). Do not hoist to shared. Same trap, lesser degree: `stopStream`, `showStep`,
   and the DOMContentLoaded body all silently diverge between files. (`onPipelineUpload` no longer
   exists — pipeline upload was removed, so this is no longer one of the divergent functions.)

4. **`DOMContentLoaded` load-order.** Both register listeners inside one big `DOMContentLoaded`; STATIC adds
   `showStep(2)` at the very end of it (auto-skip mode-select). STREAM starts on `#step1` (mode select) with
   no auto-advance. Preserve this exactly — it's the only thing that makes static "start at upload".

5. **`animateAoi` is a self-invoking rAF IIFE** started at module load, running forever regardless of step.
   In ES modules it starts on import — fine, but ensure `aoi.js` is imported on both pages or the AOI dashes
   freeze.

6. **Runtime-generated inline handlers** (`setOrigin`, `removeGcp`) are embedded in `innerHTML` strings, so
   they *require* global function names even after you `addEventListener` everything static. These are the
   handlers most likely to silently break post-modularisation. (`removePipeline`/`removePipelineAt` no
   longer exist — removed with pipeline upload.)

7. **REMOVED.** `streamPipeline` (scalar, stream) vs `streamPipelines` (array, static) no longer exist —
   pipeline upload was removed from both pages; there is no pipeline state to reconcile.

8. **Wrong `<title>` in STATIC** — says "Pravah · Stream Mode". Cosmetic, but since the task is
   behaviour-preserving, **leave it byte-identical** unless told otherwise (do not "fix" it during the split).

9. **Unused declarations kept for parity:** `gcpRowCount`, `STEP_LABELS`, `STEP_PROGRESS` are never read in
   either file. Safe to drop, but dropping changes bytes; decide with the refactor lead.

10. **`sessionConfig` is written by STATIC's `startStream` but never read** (only `drawFeedCanvas`, dead in
    static, reads it). Harmless, but a reviewer might flag it — document that it's intentional dead write.

11. **Two inline `data:image/svg+xml` select-arrow backgrounds** and JetBrains-Mono/Space-Grotesk font names
    are hard-coded in CSS and canvas `ctx.font` strings — keep verbatim; they rely on `colors_and_type.css`
    loading first.

---

## EXECUTIVE SUMMARY (10 lines)

1. The two `<style>` blocks (lines 8–740) are **byte-identical** — ship one `css/app.css`, no per-page CSS.
2. ~54 JS functions + the full state block are **byte-identical source** across both files → shared modules.
3. But STATIC only *uses* the calibration wizard (mode→upload→GCP→geometry→AOI→one PIV run); its entire
   live-dashboard JS (charts, feed, badges, polling, save-bar, RTSP probe/preview) is **dead code**.
4. Genuine divergences: `showStep`, the `DOMContentLoaded` body, and **`startStream`** (live dashboard vs
   one `/api/process` call, one result card) — `startStream` must stay split by page.
5. **Pipeline upload has been removed from both pages.** The Pipeline bar is now a fixed
   `quasi-v2 (Bodart 2024)` tag; `streamPipeline`/`streamPipelines` no longer exist; STATIC still has
   `staticVideoFile`.
6. #1 integration risk: the canvas/GCP/AOI mutable globals are written across ~15 functions and both pages —
   put them in a shared exported state object, not bare `let`s (ES-module imports are read-only bindings).
7. Inline handlers to re-wire (pre-removal counts, historical): **24 distinct in STREAM, 13 in STATIC**;
   two are generated at runtime via `innerHTML` (`setOrigin`/`removeGcp`) and *need* `window.*` names even
   after rewiring. (`removePipelineAt` no longer exists — removed with pipeline upload.)
8. Shipped split: 8 shared modules (api, state, canvas, gcp, aoi, sensor, config, wizard) + 5 stream / 4
   static page modules, grouped by concern — no `pipeline.js` on either side.
9. Latent bug: STATIC's top-level `#rtspUrl` keydown listener throws (no such element); it disappears once the
   stream probe module is excluded from the static bundle. Do not port dead stream code into static.
10. Hard rule for every worker: **DOM ids, CSS class names, and `/api/...` paths stay byte-identical** — the
    backend and stylesheet depend on them; also leave STATIC's mis-copied `<title>` untouched.
