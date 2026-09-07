/* 小光福地 Runtime · 只读管理控制台（Plugin Page）
 *
 * 使用 AstrBot 官方 Plugin Page 桥：window.AstrBotPluginPage
 * （兼容 window.parent.AstrBotPluginPage 与 debug_http 直连调试）。
 * 只读：只调用 GET /status 与 /diagnostics。 */
"use strict";

const HTTP_API = "/api/v1/plugins/extensions/astrbot_plugin_blessed_land_runtime";
const REFRESH_SECONDS = 30;

function getBridge() {
  if (window.AstrBotPluginPage) return window.AstrBotPluginPage;
  try {
    if (window.parent && window.parent !== window && window.parent.AstrBotPluginPage) {
      return window.parent.AstrBotPluginPage;
    }
  } catch (_e) { /* cross-origin */ }
  return null;
}

function isDebugHttpMode() {
  return new URLSearchParams(window.location.search).get("debug_http") === "1";
}

async function apiGet(path) {
  const bridge = getBridge();
  if (bridge && typeof bridge.apiGet === "function") {
    const payload = await bridge.apiGet(path);
    return normalize(payload);
  }
  if (isDebugHttpMode()) {
    const response = await fetch(`${HTTP_API}${path}`, { cache: "no-store" });
    const text = await response.text();
    let payload = {};
    try { payload = text ? JSON.parse(text) : {}; } catch (_e) { /* ignore */ }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return normalize(payload);
  }
  throw new Error("未检测到 AstrBot 官方插件 Page 桥接，请从 AstrBot 后台插件扩展页打开");
}

function normalize(payload) {
  if (payload && payload.success === true) return payload.data || {};
  if (payload && typeof payload.success === "boolean" && !payload.success) {
    throw new Error(payload.error || "请求失败");
  }
  return payload || {};
}

function set(id, value, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value === null || value === undefined ? "NULL" : String(value);
  el.className = cls || "";
}

function renderStatus(data) {
  set("plugin-status", data.plugin_status, "ok");
  set("runtime-version", data.runtime_version);
  set("db-integrity", data.db && data.db.integrity,
     data.db && data.db.integrity === "ok" ? "ok" : "bad");
  set("db-integrity-2", data.db && data.db.integrity,
     data.db && data.db.integrity === "ok" ? "ok" : "bad");
  set("world-status", data.world_status,
     data.world_status === "NOT_ACTIVATED" ? "warn" : "bad");
  set("world-status-2", data.world_status,
     data.world_status === "NOT_ACTIVATED" ? "warn" : "bad");
  set("blessed-tick", data.current_blessed_tick === null ? "尚未开始" : data.current_blessed_tick);
  const rate = data.natural_rate || {};
  set("current-rate", `${rate.numerator ?? "…"} / ${rate.denominator ?? "…"}`);
  set("seed", data.seed_present ? (data.world_seed_version || "PRESENT") : "NULL");
  const w = data.writer || {};
  set("writer-lease", w.lease || "Inactive", w.lease === "HELD" ? "ok" : "");
  set("writer-id", w.writer_id || "Not required");
  set("fencing-token", w.fencing_token || "Not required");
  set("db-path", data.db && data.db.path);
  set("schema-version", data.db && data.db.schema_version);
  const counts = data.entity_counts || {};
  set("c-persons", counts.persons ?? "—");
  set("c-population_groups", counts.population_groups ?? "—");
  set("c-settlements", counts.settlements ?? "—");
  set("c-tribulations", counts.tribulations ?? "—");
  set("c-world_events", counts.world_events ?? "—");
}

function renderDiagnostics(data) {
  set("d-m0", data.m0, data.m0 === "PASS" ? "ok" : "bad");
  set("d-m1", data.m1, data.m1 === "PASS" ? "ok" : "bad");
  set("d-time-engine", data.time_engine, data.time_engine === "READY" ? "ok" : "bad");
  set("d-catchup", data.offline_catchup, data.offline_catchup === "READY" ? "ok" : "bad");
  set("d-activation", data.world_activation, data.world_activation === "LOCKED" ? "ok" : "bad");
}

async function refresh() {
  try {
    const status = await apiGet("/status");
    renderStatus(status);
  } catch (err) {
    set("plugin-status", "ERROR: " + err.message, "bad");
  }
  try {
    const diag = await apiGet("/diagnostics");
    renderDiagnostics(diag);
  } catch (err) {
    set("d-m0", "ERROR", "bad");
  }
}

refresh();
setInterval(refresh, REFRESH_SECONDS * 1000);
