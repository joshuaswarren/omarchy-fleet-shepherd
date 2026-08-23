# Fleet Shepherd — Requirements

Status: **v0.1 implementation**  
Target: Omarchy Quattro / Quickshell  
Plugin ID: `io.github.joshuaswarren.fleet-shepherd`

## Functional requirements

- R1: Aggregate Herdr and OMP snapshots from one local and zero or more SSH connectors.
- R2: Show connector online/offline/stale status without removing the last valid fleet snapshot.
- R3: Show aggregate working/blocked agents, OMP request count and cost.
- R4: Filter across connector, agent, workspace, cwd, activity, model, and provider.
- R5: Entire panel is keyboard-drivable; opening the panel focuses filtering/navigation immediately.
- R6: One connector timeout or malformed response cannot block or invalidate another connector.
- R7: OMP parser accepts the current CLI’s human sync prefix before the first JSON object.

## Hard bounds

- Config: 64 KiB, 64 connectors.
- Helper final JSON: 4 MiB.
- Per subprocess: 2 MiB stdout + stderr, 8-second deadline.
- Per connector: 256 agents, 128 workspaces, 64 models, 64 folders, 256 series points.
- Remote strings: 512 characters maximum; ids/labels: 96.
- Concurrency: maximum 8 workers.

Any overrun terminates the producer and marks only that connector/source failed.

## Security requirements

- S1: No shell execution. Every command uses a fixed argv and `shell=False`.
- S2: Connector ids and SSH aliases match `^[A-Za-z0-9][A-Za-z0-9._-]*$`; leading `-`, spaces, separators, control characters, substitutions, and SSH options are rejected.
- S3: SSH is noninteractive and host-key fail-closed: BatchMode, ConnectTimeout, StrictHostKeyChecking=yes, existing known_hosts.
- S4: Config uses one no-follow, nonblocking open; symlink/FIFO/device/oversized inputs are rejected.
- S5: QML starts only the bundled helper; it never starts ssh/herdr/omp.
- S6: Remote strings render as plain text and never enter shell source, paths, URL loads, or executable notification actions.
- S7: v0.1 performs no Herdr/OMP mutation or remote focus.
- S8: Output is bounded before buffering and bounded again after parsing.

## Regression requirements from previous plugin reviews

- No non-end-anchored untrusted identifiers used in paths or output templates (YT Mini traversal review).
- No variables used before initialization; tests exercise empty/partial payloads (Remnic review).
- No unbounded StdioCollector response; producer byte caps must precede QML buffering (Soma review).
- No initial-only origin trust, redirect following, or implicit network side effects (Soma/Plex reviews).
- No FileView or test/stat/cat sequence on user-writable files; single-open no-follow/nonblocking I/O only (Plex two-round review).
- No QML `Keys` attached to PanelWindow; use focusable Item/TextInput/ListView.
- Every ListView delegate has explicit width and height.
- Preview/media files are nonempty and README claims match code.
- Model.js declarations, QML call sites, and test exports are mechanically compared without aliases.

## Release gates

- Python unittest suite passes.
- Node Model.js and QML contract tests pass.
- `qmllint` has no invalid handlers/properties/syntax failures.
- `omarchy plugin validate .` passes.
- Runtime fixture demo renders loading, partial failure, blocked, empty, and success states.
- Independent security and UX reviews return SHIP; all actionable findings fixed.
- README has install/remove/dependencies/privacy/config/keyboard/troubleshooting.
- Root LICENSE and preview.png exist and are nonempty.
