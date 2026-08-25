// Pure Fleet Shepherd presentation model. Plain script (no module syntax):
// imported by QML and loaded under node:vm in tests.

var MAX_CONNECTORS = 64
var MAX_AGENTS = 256
var MAX_MODELS = 64
var MAX_TEXT = 512

function cap(v, n) {
  var s = String(v === undefined || v === null ? "" : v)
  return s.length > n ? s.slice(0, n) : s
}

function num(v) {
  var n = Number(v)
  return isFinite(n) ? n : 0
}

function normalizeAgent(a) {
  return {
    paneId: cap(a.paneId || a.pane_id, 96),
    agent: cap(a.agent, 96),
    status: cap(a.status || a.agent_status || "unknown", 32).toLowerCase(),
    activity: cap(a.activity || a.title || a.terminal_title_stripped || a.terminal_title, MAX_TEXT),
    cwd: cap(a.cwd || a.foreground_cwd, MAX_TEXT),
    workspace: cap(a.workspace || a.workspaceLabel || "", 128),
    focused: a.focused === true
  }
}

function normalizeConnector(c) {
  var agents = []
  var rawAgents = c && c.herdr && Array.isArray(c.herdr.agents) ? c.herdr.agents : []
  for (var i = 0; i < rawAgents.length && i < MAX_AGENTS; i++) agents.push(normalizeAgent(rawAgents[i] || {}))
  var models = []
  var rawModels = c && c.omp && Array.isArray(c.omp.byModel) ? c.omp.byModel : []
  for (var m = 0; m < rawModels.length && m < MAX_MODELS; m++) {
    var x = rawModels[m] || {}
    models.push({ model: cap(x.model, 128), provider: cap(x.provider, 128), requests: num(x.totalRequests || x.requests), cost: num(x.totalCost || x.cost) })
  }
  var herdrIdle = !!(c && c.herdr && c.herdr.idle === true)
  if (herdrIdle) agents = []
  return {
    id: cap(c.id, 96),
    label: cap(c.label || c.id, 96),
    herdrIdle: herdrIdle,
    health: cap(c.health || "offline", 32),
    latencyMs: Math.max(0, num(c.latencyMs)),
    error: cap(c.error, 256),
    focusTarget: cap(c.focusTarget || c.id, 96),
    herdrPresent: !!(c && c.herdr && Array.isArray(c.herdr.agents)),
    ompPresent: !!(c && c.omp && c.omp.overall),
    agents: agents,
    overall: c && c.omp && c.omp.overall ? {
      requests: num(c.omp.overall.totalRequests || c.omp.overall.requests),
      cost: num(c.omp.overall.totalCost || c.omp.overall.cost),
      tokens: num(c.omp.overall.totalInputTokens) + num(c.omp.overall.totalOutputTokens),
      errorRate: num(c.omp.overall.errorRate)
    } : { requests: 0, cost: 0, tokens: 0, errorRate: 0 },
    models: models
  }
}

function summarize(connectors) {
  var s = { connectors: connectors.length, online: 0, stale: 0, offline: 0, working: 0, blocked: 0, requests: 0, cost: 0 }
  for (var i = 0; i < connectors.length; i++) {
    var c = connectors[i]
    if (c.health === "online" || c.health === "degraded") s.online++
    else if (c.health === "stale") s.stale++
    else s.offline++
    s.requests += c.overall.requests
    s.cost += c.overall.cost
    for (var j = 0; c.herdrPresent && !c.herdrIdle && j < c.agents.length; j++) {
      if (c.agents[j].status === "working") s.working++
      if (c.agents[j].status === "blocked") s.blocked++
    }
  }
  return s
}

function normalizeSnapshot(raw) {
  if (!raw || Number(raw.schemaVersion) !== 1 || !Array.isArray(raw.connectors)) throw new Error("invalid fleet snapshot")
  var connectors = []
  for (var i = 0; i < raw.connectors.length && i < MAX_CONNECTORS; i++) connectors.push(normalizeConnector(raw.connectors[i] || {}))
  return { schemaVersion: 1, generatedAt: cap(raw.generatedAt, 64), connectors: connectors, summary: summarize(connectors) }
}

function matches(haystack, query) {
  return String(haystack || "").toLowerCase().indexOf(query) >= 0
}

function filterConnectors(connectors, filterText, view) {
  var q = cap(filterText, 128).toLowerCase().trim()
  var out = []
  for (var i = 0; i < connectors.length; i++) {
    var c = connectors[i]
    var agents = []
    for (var j = 0; j < c.agents.length; j++) {
      var a = c.agents[j]
      if (view === "attention" && a.status !== "blocked") continue
      if (q && !matches(c.label + " " + a.agent + " " + a.activity + " " + a.cwd + " " + a.workspace, q)) continue
      agents.push(a)
    }
    var connectorMatch = !q || matches(c.label + " " + c.id + " " + c.health + " " + c.models.map(function(m){ return m.model + " " + m.provider }).join(" "), q)
    // Idle Herdr = no attached session: usage still displays, agents never do.
    var hasDisplay = (c.herdrPresent && !c.herdrIdle && c.agents.length > 0) || (c.ompPresent && c.overall && c.overall.requests > 0)
    if (!hasDisplay) continue
    if (!c.herdrPresent && !c.ompPresent) continue
    if (c.herdrPresent && c.herdrIdle && !c.ompPresent) continue
    if (!c.herdrPresent && c.ompPresent && c.overall.requests === 0) continue
    if (view === "usage") { if (connectorMatch) out.push(Object.assign({}, c, { agents: [] })); continue }
    if (agents.length || (view !== "attention" && connectorMatch)) out.push(Object.assign({}, c, { agents: agents }))
  }
  return out
}

function money(v) {
  return "$" + num(v).toFixed(2)
}

function compact(n) {
  n = num(n)
  if (n >= 1000000) return (n / 1000000).toFixed(n >= 10000000 ? 0 : 1) + "M"
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "K"
  return String(Math.round(n))
}

function statusColor(status) {
  if (status === "blocked" || status === "offline") return "urgent"
  if (status === "working" || status === "online") return "accent"
  return "muted"
}

// Retain per-source last-good data across transient connector failures. A
// connector becomes stale only when old data was actually reused; its fresh
// error message and latency remain visible. Never carry data between ids.
function mergeSnapshot(previous, next) {
  if (!previous || !Array.isArray(previous.connectors)) return next
  var oldById = {}
  for (var i = 0; i < previous.connectors.length; i++) oldById[previous.connectors[i].id] = previous.connectors[i]
  var merged = []
  for (var j = 0; j < next.connectors.length; j++) {
    var fresh = next.connectors[j]
    var old = oldById[fresh.id]
    var reused = false
    if (old && (fresh.health === "degraded" || fresh.health === "offline")) {
      if (!fresh.herdrPresent && old.herdrPresent) { fresh.agents = old.agents; fresh.herdrPresent = true; reused = true }
      if (!fresh.ompPresent && old.ompPresent) { fresh.models = old.models; fresh.overall = old.overall; fresh.ompPresent = true; reused = true }
      if (reused) fresh.health = "stale"
    }
    merged.push(fresh)
  }
  return { schemaVersion: 1, generatedAt: next.generatedAt, connectors: merged, summary: summarize(merged) }
}

function markAllStale(snapshot, message) {
  if (!snapshot || !Array.isArray(snapshot.connectors)) return snapshot
  var connectors = []
  for (var i = 0; i < snapshot.connectors.length; i++) {
    var c = snapshot.connectors[i]
    connectors.push(Object.assign({}, c, {
      health: c.health === "offline" ? "offline" : "stale",
      error: c.error || cap(message, 256)
    }))
  }
  return { schemaVersion: 1, generatedAt: snapshot.generatedAt, connectors: connectors, summary: summarize(connectors) }
}
