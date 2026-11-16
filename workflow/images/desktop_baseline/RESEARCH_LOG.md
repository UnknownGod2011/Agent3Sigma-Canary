# AgentCanary Desktop/UI Research Log

**Updated:** 2026-11-16 23:59 IST  
**Research branch:** `research/desktop-ui-baseline`  
**Branch tip before this audit entry:** `3569a31a5afa25a3e8302d9f75c1135a0067b3e8`  
**Last implementation revision validated by the three CI workflows:** `c6562cecd4805bb2c93997cf6210630cdaf8fd46`  
**Fork master HEAD:** `5072b78260d6dfe16f28a479ae83db4ef5c86bce`  
**Canonical upstream master HEAD:** `a03a36613feab18689d22b19243d8787d65f341d`  
**Comparison at reviewed branch tip:** 207 commits ahead of upstream / 19 behind; 207 ahead of fork master / 0 behind  
**Canonical upstream:** [antgroup/Agent3Sigma-Canary](https://github.com/antgroup/Agent3Sigma-Canary)

This file is a public, technical summary of the desktop/UI-agent feasibility work. It intentionally excludes private correspondence and personal workflow notes.

## Objective

Establish whether AgentCanary's existing task, Docker environment, agent invocation, transcript, and grading lifecycle can evaluate a controlled task that requires interaction with a genuine desktop GUI.

The first milestone is integration feasibility. It does **not** include security fault injection or claims about autonomous visual-reasoning quality.

## Prototype

The experimental desktop image preserves the existing OpenClaw-compatible runner contract and adds:

- An Xvfb/X11 virtual display and a deterministic Tk Notes application.
- Screenshot observation and mouse/keyboard interaction through `desktopctl`.
- A task that requires replacing the note through the visible GUI and invoking the real Save callback.
- Transcript-aware, fail-closed grading that checks the screenshot/tool evidence, GUI actions, exact final state, and exactly one Save callback.
- A host-side grading path that receives the task's state artifact after the Docker execution lifecycle.

The task and supporting implementation are under:

- `tasks/desktop_baseline/task_9000_desktop_notes_gui.md`
- `workflow/images/desktop_baseline/`

## Artifact handoff investigation

The desktop task produces a small machine-checkable state artifact inside the container, while grading is performed by the host-side AgentCanary runner. The research branch compares two ways to make that artifact available to grading:

1. **Bounded container export:** read an allowlisted, size-bounded artifact through `docker exec`, validate it, and place it in the host task workspace before teardown.
2. **Task-scoped bind mount:** mount a fresh host temporary directory at `/tmp/agentcanary-desktop`, stop the container, validate the retained regular file, and copy it into the host task workspace before the existing grading call.

The bind-mount experiment rejects unsafe file types and metadata (including symlinks, hard links, non-regular files, and oversized artifacts). A no-mount/no-copyback negative control verifies that host-side grading fails when the required state artifact is not transferred.

The upstream discussion is about whether AgentCanary should expose a general, opt-in task-scoped artifact-handoff mechanism for outputs needed by post-run grading, and which lifecycle/interface is preferred. This is a design question, not a claim that the existing runner is broken.

## Validation status

All three latest workflows completed successfully on implementation revision `c6562cecd4805bb2c93997cf6210630cdaf8fd46`:

- [Desktop reference lifecycle](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43787168606)
- [Desktop baseline smoke test](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43787168601)
- [Desktop compatibility against upstream master](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43787168589)

The smoke workflow's evidence-parser regression suite now also covers Python-glob state-file write attempts and shell-glob expansion into an otherwise allowed `desktopctl type` command; both are rejected by the fail-closed grader.

The reference-lifecycle workflow repeated the task-scoped bind-mount handoff and native OpenClaw CLI tool loop against a deterministic local provider. Positive runs scored **1.0/1.0**; the no-mount/no-copyback controls scored **0.0/1.0** after the GUI task had run in the container, confirming that host-side grading depends on the transferred state artifact.

The compatibility workflow fetched current upstream master at `a03a36613feab18689d22b19243d8787d65f341d`, ran the desktop adapter regression suite against that runner, built a desktop-compatible image from the upstream image-builder context, and repeated the reference and local OpenClaw paths. Its positive runs scored **1.0/1.0** and its no-mount control scored **0.0/1.0**. The workflow therefore validates the overlay against that exact upstream revision; it does **not** mean the research branch has been merged or rebased onto upstream. The branch remains 19 commits behind upstream master.

The local provider uses a scripted plan and Tesseract OCR. These runs validate screenshot-conditioned tool/runner integration and reproducibility, **not** autonomous visual reasoning or live-model quality. The optional Gemini model job was skipped; no live-model success is claimed.

## Claim boundaries and limitations

- The OCR reference controller and local OpenClaw provider use deterministic Tesseract-based screenshot localization and a scripted plan. They validate integration and reproducibility, **not** autonomous visual reasoning or live-model quality.
- The experimental container is not a security boundary. The current setup does not establish OS-level isolation between an evaluated agent and the GUI state. Do not use it to claim resistance to a hostile agent.
- Security scenarios such as stale UI state, misleading confirmations, or partial execution remain future work after the baseline and trust boundary are reviewed.

## Upstream discussion status

- [Issue #2: Question: task-scoped artifact handoff for Docker-backed grading](https://github.com/antgroup/Agent3Sigma-Canary/issues/2) remains open with no maintainer comments as of this update. It records the concrete handoff problem, the two prototype approaches, observed validation, explicit limitations, and asks maintainers for the preferred integration mechanism.
- The research branch is [available here](https://github.com/UnknownGod2011/Agent3Sigma-Canary/tree/research/desktop-ui-baseline) for implementation review.
- No pull request has been opened. The next step is to get architectural feedback on the artifact-handoff boundary and preferred integration shape before preparing a focused draft PR.


## Independent artifact and repository audit — 2026-11-16 10:59 IST

- Rechecked repository refs immediately before this entry: upstream master `a03a36613feab18689d22b19243d8787d65f341d`, fork master `5072b78260d6dfe16f28a479ae83db4ef5c86bce`, and research-branch tip `6ea431f75fb6ecac8c0fd28ebed823cd95354ceb`. The branch is 205 commits ahead of upstream and 19 behind; it is 205 commits ahead of fork master and 0 behind. The latest branch-tip commit is a research-log update; the implementation revision exercised by CI is `c6562cecd4805bb2c93997cf6210630cdaf8fd46`.
- Downloaded and inspected the deterministic lifecycle artifact from [run 43787168606](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43787168606). Its manifest records eight positive runs (reference controller, local OpenClaw provider, and task-scoped bind-mount variants, each repeated) at **1.0/1.0**, plus two no-copyback/no-bind-mount controls at **0.0/1.0**. All eight final-state artifacts have the same SHA-256; each repeated pair has an identical ordered GUI-action-sequence hash.
- Decoded the local OpenClaw-provider screenshots from the retained result JSON. They are valid 800×600 PNGs of the actual Tk Notes window: the initial frame shows the seeded note, and the post-edit frame shows the requested text before Save. The independently retained final state is `{"current_text":"AgentCanary desktop baseline complete","save_count":1,"saved":true,"text":"AgentCanary desktop baseline complete"}`.
- The reference-lifecycle logs show the X11/Tk preflight and automated grading passing. OpenClaw Gateway startup closed abnormally in the local-provider runs and the runner fell back to the embedded CLI path; therefore this evidence supports the CLI/tool-loop integration, not a claim that Gateway mode is stable.
- The smoke, reference-lifecycle, and upstream-compatibility workflows all completed successfully. The optional `gemini-model-e2e` job was skipped by its explicit opt-in condition: this was a push without the `[run-live-model]` marker, and the manual-dispatch input defaults to false. This is not a provider failure and does not establish whether Gemini secrets are configured; no secret values were accessed.
- Fresh issue/PR inventory: issue [#2](https://github.com/antgroup/Agent3Sigma-Canary/issues/2) is the only open issue and still has no maintainer comments; there are no other closed issues or open PRs returned. PR [#1](https://github.com/antgroup/Agent3Sigma-Canary/pull/1), the NARA-Bench/native-runtime integration, is merged. No PR authored by `UnknownGod2011` was found. No new upstream issue or PR was created.
- Implementation work in this audit: no code changes. Files changed by this entry: this research log only. No local tests were run; the exact CI results above were produced by GitHub Actions on the implementation revision, not by this documentation update.
- Unresolved: maintainer preference for bounded export versus task-scoped bind mount; live-model visual reasoning; and a genuine agent/GUI isolation boundary. The current container runs as root and must not support security-robustness claims.
- Highest-value next step: keep issue #2 as the single public design discussion and wait for maintainer feedback. Only prepare a focused draft PR after agreeing on the artifact-handoff interface and extracting the minimal desktop changes onto current upstream; the present branch is 19 commits behind and should not be proposed as a whole. A live-model run requires explicit workflow opt-in, configured credentials, and approval for possible provider cost.

## Independent lifecycle and upstream compatibility recheck — 2026-11-16 19:31 IST

- Rechecked repository refs: canonical upstream master `a03a36613feab18689d22b19243d8787d65f341d`, fork master `5072b78260d6dfe16f28a479ae83db4ef5c86bce`, and research branch `73046b0cff7c03df6b0a01765ca66374a5d62535`. The branch is 206 commits ahead of upstream and 19 behind; it is 206 commits ahead of fork master and 0 behind. The upstream delta since the fork base is the merged NARA-Bench/native-runtime integration (PR #1); no later upstream commit was observed.
- Re-ran the repository/issue inventory: upstream issue #2 remains open with no comments; PR #1 is merged; no closed upstream issues or additional upstream PRs were returned. No maintainer feedback or new public action was observed.
- Verified the three workflows on branch commit `73046b0cff7c03df6b0a01765ca66374a5d62535`: [desktop smoke](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43811414708), [upstream compatibility](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43811414645), and [reference lifecycle](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43811414624) all completed successfully. The optional Gemini/live-model job was skipped by its explicit opt-in condition; no live-model result is claimed.
- Inspected the retained artifacts from the latest reference and compatibility runs. On the exact upstream SHA above, repeated reference-controller and native OpenClaw local-provider runs scored 1.0/1.0; task-scoped bind-mount repeats also scored 1.0/1.0. Repeated pairs had identical final-state bytes, ordered GUI-action hashes, and screenshot hashes. The no-copyback and no-bind-mount controls scored 0.0/1.0. The compatibility artifact records two screenshot/read pairs and the five GUI actions (editor click, Home, Shift+End, exact text entry, Save click); decoded screenshots show the real Tk Notes window before and after editing. This remains deterministic integration evidence, not autonomous visual-reasoning or live-model-quality evidence.
- Re-read the current upstream runner lifecycle and the overlay adapter: AgentCanary starts the Docker container, runs deferred `run_command` pre-setup, invokes `execute_openclaw_task`, copies transcripts through the adapter, calls `docker.stop()`, and then calls host-side `grade_task()`. The wrapper intercepts that stop boundary to export the grader-only state artifact before teardown. The compatibility workflow separately fetches current upstream master, overlays only the desktop fixture/task, and repeats the lifecycle there.
- Implementation work: no runtime or grading code changed. This entry and the header ref reconciliation are the only files changed in this audit. No local tests were run; the exact GitHub Actions runs above are the checks that executed.
- Public actions: no upstream issue, PR, or comment was created. Issue #2 remains the single public design discussion. No fork PR was opened.
- Unresolved: maintainer preference for bounded container export versus a task-scoped bind mount; live-model visual grounding; and the container/agent trust boundary (the fixture runs as root and is not a security isolation mechanism). The research branch remains 19 commits behind current upstream and should not be proposed wholesale.
- Highest-value next step: wait for architectural feedback on issue #2. If maintainers prefer a handoff shape, extract only the minimal compatible adapter/API onto a branch based on current upstream and rerun the compatibility workflow before considering a draft PR. Do not add security fault injection or claim autonomous visual reasoning from the current scripted/Tesseract evidence.



## Artifact-handoff API boundary review — 2026-11-16 23:59 IST

- Rechecked refs immediately before this entry: canonical upstream master `a03a36613feab18689d22b19243d8787d65f341d`, fork master `5072b78260d6dfe16f28a479ae83db4ef5c86bce`, and research branch `3569a31a5afa25a3e8302d9f75c1135a0067b3e8`. The research branch is 207 commits ahead of upstream and 19 behind; it is 207 commits ahead of fork master and 0 behind.
- Re-read the current upstream Docker/benchmark lifecycle. `scripts/lib_docker.py` already exposes low-level `start(extra_mounts=...)` bind-mount support, and `scripts/benchmark.py` passes mounts currently derived from required skills. The runner does not expose a task-frontmatter contract for arbitrary grader artifacts. The task runner calls `docker.stop()` before host-side `grade_task()`; `ensure_transcripts_on_host()` exports agent session files, not arbitrary task-generated artifacts. Issue #2 should therefore distinguish existing low-level bind-mount capability from the missing task-scoped artifact lifecycle / pre-teardown grading handoff contract.
- Rechecked upstream discussions: issue [#2](https://github.com/antgroup/Agent3Sigma-Canary/issues/2) remains open with no comments; PR [#1](https://github.com/antgroup/Agent3Sigma-Canary/pull/1) remains the only upstream PR and is merged. No PR authored by `UnknownGod2011`, no new desktop/UI duplicate, and no maintainer response were found.
- Verified the three latest workflows on research branch commit `3569a31`: [desktop smoke](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43883829183), [upstream compatibility](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43883829320), and [reference lifecycle](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43883829192) all completed successfully. The compatibility workflow fetched current upstream SHA `a03a366` in an isolated checkout and overlaid only the desktop fixture/task and helpers, not the research branch's modified core runner.
- Inspected compatibility artifact `14232684279` from run `43883829320`. The reference controller and deterministic local OpenClaw provider each completed repeated runs at 1.0/1.0; each run recorded five GUI actions and two screenshot observations delivered through image-bearing `read` results. Repeated screenshots, ordered GUI actions, and final-state bytes had identical SHA-256 hashes. The no-bind-mount negative control scored 0.0/1.0. Direct artifact inspection confirmed valid 800x600 PNGs of the actual Tk Notes window before and after editing, with the target text visible before the single Save click.
- The Gemini/live-model job was skipped by its explicit opt-in condition. The provider is scripted and uses Tesseract OCR, so this is deterministic GUI/tool/transcript/grading integration evidence, not autonomous visual reasoning or live-model quality. The image still runs the fixture and agent as container root; it is not a security isolation boundary.
- Implementation: no runtime or grading code changed. This entry records the API-boundary finding and current evidence only. Local Docker execution was unavailable in this environment, so no local container run is claimed; the cited checks are GitHub Actions runs.
- Public actions: none. Issue #2 remains the single design discussion; no issue, comment, or PR was created in this run.
- Unresolved: maintainer preference for bounded export versus a task-scoped bind mount / lifecycle hook; autonomous visual grounding; and a genuine agent/GUI isolation boundary. The research branch remains 19 commits behind upstream and should not be proposed wholesale.
- Highest-value next step: wait for maintainer feedback on issue #2. If maintainers point to the existing `extra_mounts` API, clarify that mount creation is already available but task-scoped artifact capture before teardown is not. Only then prepare a minimal extraction based on current upstream and rerun the compatibility workflow; do not add security fault injection or claim autonomous visual reasoning.
