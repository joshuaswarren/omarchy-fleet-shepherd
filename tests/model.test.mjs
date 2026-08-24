import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import vm from "node:vm"

const source = readFileSync(new URL("../Model.js", import.meta.url), "utf8")
const ctx = vm.createContext({})
vm.runInNewContext(source + "\nthis.M={normalizeSnapshot,mergeSnapshot,markAllStale,filterConnectors,money,compact,statusColor}", ctx)
const M = ctx.M

const raw = {
  schemaVersion: 1,
  generatedAt: "2026-08-23T12:00:00Z",
  connectors: [
    { id: "local", label: "This machine", health: "online", latencyMs: 10,
      herdr: { agents: [
        { paneId: "p1", agent: "omp", status: "working", activity: "Build plugin", cwd: "/src/project", workspace: "plugins" },
        { paneId: "p2", agent: "omp", status: "blocked", activity: "Needs answer", cwd: "/src/api", workspace: "api" }
      ]},
      omp: { overall: { totalRequests: 10, totalCost: 1.25, totalInputTokens: 100, totalOutputTokens: 20 }, byModel: [{ model: "gpt", provider: "openai", totalRequests: 10, totalCost: 1.25 }] } },
    { id: "remote", label: "Connector A", health: "offline", error: "timeout", herdr: { agents: [] }, omp: { overall: { totalRequests: 0, totalCost: 0 }, byModel: [] } }
  ]
}

test("normalizeSnapshot aggregates fleet summary", () => {
  const x = M.normalizeSnapshot(raw)
  assert.equal(x.connectors.length, 2)
  assert.equal(x.summary.online, 1)
  assert.equal(x.summary.offline, 1)
  assert.equal(x.summary.working, 1)
  assert.equal(x.summary.blocked, 1)
  assert.equal(x.summary.requests, 10)
  assert.equal(x.summary.cost, 1.25)
})

test("normalizes snake-case Herdr pane fields", () => {
  const x = M.normalizeSnapshot({ schemaVersion: 1, connectors: [{ id:"x", health:"online", herdr:{agents:[{pane_id:"w:p",agent_status:"working",terminal_title_stripped:"Title",foreground_cwd:"/x"}]},omp:{} }] })
  assert.equal(x.connectors[0].agents[0].paneId, "w:p")
  assert.equal(x.connectors[0].agents[0].activity, "Title")
})

test("attention view keeps only blocked agents", () => {
  const x = M.normalizeSnapshot(raw)
  const out = M.filterConnectors(x.connectors, "", "attention")
  assert.equal(out.length, 1)
  assert.equal(out[0].agents.length, 1)
  assert.equal(out[0].agents[0].status, "blocked")
})

test("filter matches connector agent activity cwd workspace and model", () => {
  const x = M.normalizeSnapshot(raw)
  for (const q of ["laptop", "build", "/src/api", "plugins", "openai"]) assert.equal(M.filterConnectors(x.connectors, q, "overview").length, 1)
  assert.equal(M.filterConnectors(x.connectors, "missing", "overview").length, 0)
})

test("usage view omits agents", () => {
  const x = M.normalizeSnapshot(raw)
  const out = M.filterConnectors(x.connectors, "", "usage")
  assert.equal(out.length, 2)   // both have omp data; usage view keeps them
  assert.equal(out[0].agents.length, 0)
})

test("rejects invalid schema", () => {
  assert.throws(() => M.normalizeSnapshot({ schemaVersion: 2, connectors: [] }))
  assert.throws(() => M.normalizeSnapshot({ schemaVersion: 1 }))
})

test("bounds connectors agents models and strings", () => {
  const connectors = Array.from({length:80}, (_,i)=>({id:"x"+i,label:"L".repeat(600),health:"online",herdr:{agents:Array.from({length:300},()=>({agent:"a"}))},omp:{byModel:Array.from({length:100},()=>({model:"m"}))}}))
  const x = M.normalizeSnapshot({schemaVersion:1,connectors})
  assert.equal(x.connectors.length,64)
  assert.equal(x.connectors[0].agents.length,256)
  assert.equal(x.connectors[0].models.length,64)
  assert.equal(x.connectors[0].label.length,96)
})

test("format helpers are deterministic", () => {
  assert.equal(M.money(1.2), "$1.20")
  assert.equal(M.compact(1500), "1.5K")
  assert.equal(M.compact(2500000), "2.5M")
  assert.equal(M.statusColor("blocked"), "urgent")
  assert.equal(M.statusColor("working"), "accent")
})


test("mergeSnapshot keeps last-good connector data and marks stale", () => {
  const old = M.normalizeSnapshot(raw)
  const fresh = M.normalizeSnapshot({schemaVersion:1,connectors:[{id:"local",label:"This machine",health:"offline",error:"timeout",herdr:null,omp:null}]})
  const merged = M.mergeSnapshot(old,fresh)
  assert.equal(merged.connectors[0].health,"stale")
  assert.equal(merged.connectors[0].agents.length,2)
  assert.equal(merged.connectors[0].overall.requests,10)
  assert.equal(merged.connectors[0].error,"timeout")
  assert.equal(merged.summary.stale,1)
})

test("mergeSnapshot never carries data across connector ids", () => {
  const old=M.normalizeSnapshot(raw)
  const fresh=M.normalizeSnapshot({schemaVersion:1,connectors:[{id:"new",label:"New",health:"offline",herdr:null,omp:null}]})
  const merged=M.mergeSnapshot(old,fresh)
  assert.equal(merged.connectors[0].agents.length,0)
  assert.equal(merged.connectors[0].health,"offline")
})


test("markAllStale preserves data and marks truthfully",()=>{
 const old=M.normalizeSnapshot(raw); const stale=M.markAllStale(old,"refresh failed");
 assert.equal(stale.connectors[0].health,"stale"); assert.equal(stale.connectors[0].agents.length,2);
 assert.equal(stale.connectors[0].error,"refresh failed"); assert.equal(stale.summary.stale,1);
})

test("successful empty Herdr does not resurrect old agents",()=>{
 const old=M.normalizeSnapshot(raw)
 const next=M.normalizeSnapshot({schemaVersion:1,connectors:[{id:"local",label:"This machine",health:"degraded",herdr:{agents:[]},omp:null}]})
 const merged=M.mergeSnapshot(old,next)
 assert.equal(merged.connectors[0].agents.length,0)
 assert.equal(merged.connectors[0].models.length,1)
 assert.equal(merged.connectors[0].health,"stale")
})

test("idle Herdr hides agents but keeps usage in fleet totals", () => {
  const doc = { schemaVersion: 1, connectors: [
    { id: "w1", label: "Worker", health: "online", herdr: { agents: [{ agent: "omp", status: "working" }], idle: true }, omp: { overall: { totalRequests: 5, totalCost: 0.5 }, byModel: [] } }
  ]}
  const x = M.normalizeSnapshot(doc)
  assert.equal(x.summary.working, 0)        // idle session: agent not counted
  assert.equal(x.summary.requests, 5)       // usage still counted
  const agents = M.filterConnectors(x.connectors, "", "overview")
  assert.equal(agents[0].agents.length, 0)  // agent row hidden
})
