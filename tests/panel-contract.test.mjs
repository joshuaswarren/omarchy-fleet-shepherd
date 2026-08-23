import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

const panel = readFileSync(new URL("../Panel.qml", import.meta.url), "utf8")
const bar = readFileSync(new URL("../BarWidget.qml", import.meta.url), "utf8")
const helper = readFileSync(new URL("../bin/fleet-snapshot", import.meta.url), "utf8")

test("QML starts only the bundled helper and bounds before JSON.parse", () => {
  assert.match(panel, /command = \["python3", helper\]/)
  assert.match(bar, /command = \["python3", root\.helper\]/)
  assert.doesNotMatch(panel + bar, /\["ssh"|\["herdr"|\["omp"|bash", "-c|sh", "-c/)
  assert.match(panel, /raw\.length > 4194304/)
  assert.match(bar, /raw\.length>4194304/)
})

test("keyboard and list contracts avoid prior QML failures", () => {
  const windowStart = panel.indexOf("PanelWindow {")
  const inputStart = panel.indexOf("TextInput {", windowStart)
  assert.ok(inputStart > windowStart)
  // Keys belong to a focusable TextInput, never PanelWindow itself.
  assert.doesNotMatch(panel.slice(windowStart, inputStart), /Keys\./)
  assert.match(panel.slice(inputStart), /Keys\.onUpPressed/)
  assert.match(panel.slice(inputStart), /Keys\.onEscapePressed/)
  assert.match(panel, /delegate: Item[\s\S]{0,900}width: ListView\.view\.width[\s\S]{0,250}height: 68/)
  assert.match(panel, /textFormat:\s*Text\.PlainText/)
  assert.doesNotMatch(panel, /FileView\s*\{/)
})

test("backend enforces fixed argv and fail-closed SSH", () => {
  assert.match(helper, /shell=False/)
  assert.match(helper, /BatchMode=yes/)
  assert.match(helper, /StrictHostKeyChecking=yes/)
  assert.match(helper, /os\.O_NOFOLLOW \| os\.O_NONBLOCK/)
  assert.match(helper, /OUTPUT_MAX_BYTES = 2 \* 1024 \* 1024/)
  assert.match(helper, /FINAL_MAX_BYTES = 4 \* 1024 \* 1024/)
  assert.doesNotMatch(helper, /StrictHostKeyChecking=no|accept-new|UserKnownHostsFile=\/dev\/null|shell=True/)
})
