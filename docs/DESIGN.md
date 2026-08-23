# Fleet Shepherd — Design

Status: v0.1 implementation contract  
Plugin ID: `io.github.joshuaswarren.fleet-shepherd`

## Problem

Herdr Agents answers “what are my agents doing?” for one Herdr server. OMP Stats answers “what did this OMP instance consume?” for one local OMP database. A connector fleet turns those into separate terminals and separate dashboards, so blocked work and spend disappear behind host boundaries.

Fleet Shepherd presents one read-only operational snapshot: connector health, Herdr activity, and OMP aggregate usage across local and SSH connectors.

## v0.1 scope

- Local connector is always available.
- Optional SSH connectors are read from `~/.config/fleet-shepherd/connectors.json`.
- Each connector runs exactly two fixed commands:
  - `herdr api snapshot`
  - `omp stats --json`
- One bounded helper response drives one QML panel.
- Panel views: Overview, Needs Attention, Agents, Usage.
- Keyboard-first filter and navigation.
- Last-good snapshot remains visible while a refresh is running or a connector fails.

## Non-goals

- No cancel/restart/send-input actions.
- No remote TUI keystroke injection.
- No credentials or SSH keys stored by the plugin.
- No central database, history, billing ledger, or raw session ingestion.
- No network listener or elevated service.

Remote control comes only after Herdr exposes a verified authenticated action API. Navigation may be added later as a separate, allowlisted helper command.

## Architecture

```text
BarWidget.qml ──toggle──> Panel.qml
                            │
                            └─ Process [python3, bin/fleet-snapshot]
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    │                                                   │
            local subprocesses                                  fixed SSH argv
       herdr api snapshot                                herdr api snapshot
       omp stats --json                                   omp stats --json
                    │                                                   │
                    └──────────── bounded normalized JSON ─────────────┘
                                              │
                                           Model.js
                                   validation/filter/grouping
```

QML never starts SSH, Herdr, or OMP directly. It starts one helper with a fixed argv. The helper owns timeouts, process groups, output ceilings, normalization, and connector isolation.

Bar and panel call the same helper through a 15-second runtime cache under `$XDG_RUNTIME_DIR/fleet-shepherd`. A mode-0600 flock serializes refresh; simultaneous callers recheck after locking and return the same atomic snapshot. Cache reads are no-follow, owner-only, regular-file and 4 MiB bounded. Right-click/Ctrl+R force collection; normal polls are cheap cache hits.

## Connector configuration

```json
{
  "schemaVersion": 1,
  "connectors": [
    { "id": "laptop", "label": "This machine", "mode": "local" },
    { "id": "connector-a", "label": "Connector A", "mode": "ssh", "target": "connector-a" }
  ]
}
```

SSH `target` is an OpenSSH host alias, not a command or URL. It is restricted to `[A-Za-z0-9._-]`, cannot begin with `-`, and is passed as one argv element after fixed SSH options. Authentication, proxies, usernames, ports, identities, and known-host fingerprints belong in `~/.ssh/config` and `known_hosts`, not plugin JSON.

## Snapshot schema

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-08-23T12:00:00Z",
  "summary": {
    "connectors": 3,
    "online": 2,
    "stale": 1,
    "working": 7,
    "blocked": 1,
    "requests": 1042,
    "cost": 42.17
  },
  "connectors": [
    {
      "id": "laptop",
      "label": "This machine",
      "health": "online",
      "latencyMs": 180,
      "error": "",
      "herdr": { "agents": [], "workspaces": [] },
      "omp": { "overall": {}, "byModel": [] }
    }
  ]
}
```

Every collection and string is bounded in the helper and revalidated in Model.js. Remote panes may contain project paths and terminal titles; the panel renders them as plain text only.

## Refresh and staleness

- Default refresh: 15 seconds; configurable 5–300 seconds.
- Connector timeouts: Herdr 8 seconds, OMP stats 45 seconds; fleet deadline 60 seconds.
- Connector queries run concurrently with a small worker ceiling.
- One connector failure never blocks another.
- Panel retains the last valid snapshot and marks stale/offline connectors.
- Helper output is one document with a hard maximum size; QML rejects anything beyond that ceiling.

## Security model

- Closed subprocess argv tables; `shell=False` always.
- No settings-controlled executable or command string.
- SSH: `BatchMode=yes`, short timeout, `StrictHostKeyChecking=yes`; no TOFU, no `/dev/null` known_hosts, no ProxyCommand injection.
- Config read: single descriptor open with `O_NOFOLLOW|O_NONBLOCK`, regular-file/type/size validation, maximum 64 KiB.
- Per-command output is read incrementally and the process group is killed at the byte cap or deadline.
- Parsed output caps: connectors, agents, workspaces, models, folders, series points, and string lengths.
- No FileView on user-writable JSON.
- No remote string enters rich text, shell source, local paths, notifications with executable actions, or an IPC command.
- The plugin is read-only in v0.1.

## UX

Bar: sheep/Pi mark plus `working · blocked · cost`, urgent when blocked, muted when every connector is stale/offline.

Panel header: fleet freshness, refresh, close. Summary strip: connectors online, active agents, blocked count, aggregate requests/cost. Connector rows show up to three agents in overview, all attention rows up to the safety cap, and top OMP models in Usage. Typing filters immediately; arrows navigate; `Ctrl+R` refreshes; `1–4` switches views; `Esc` clears filter then closes.

The first screen answers three questions without clicking:

1. Is every connector reachable?
2. Does any agent need attention?
3. What is the fleet’s OMP usage today?
