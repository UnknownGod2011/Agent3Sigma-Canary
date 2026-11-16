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


## Desktop image metadata and CI follow-up — 2026-11-17 01:09 IST

- Refs rechecked: upstream master `a03a36613feab18689d22b19243d8787d65f341d`; fork master `5072b78260d6dfe16f28a479ae83db4ef5c86bce`; research branch `0806c95aeca9ed9d6c9839a68c6c62ff958e4892`. Research branch is 211 commits ahead of upstream and 19 behind; 211 ahead of fork master and 0 behind. Do not propose this branch wholesale.
- Attempted to recover the durable Google Doc `AgentCanary Contribution Ledger — Tanush Shah` by exact title and document ID through the available Library search; no matching document was returned, and no Google Drive/Docs connector is available in this session. Used this repository log as the available technical record; the Google Doc remains an external blocker.
- Re-read upstream README, task-format and pre-setup docs, `scripts/benchmark.py`, `scripts/lib_docker.py`, `scripts/lib_agent.py`, task loading/grading code, and the desktop task, Dockerfile, handoff/export helpers and CI workflows. The current lifecycle remains: task frontmatter/load -> deferred `run_command` setup -> Docker image/runtime -> OpenClaw invocation -> transcript export -> `docker.stop()` -> host-side `grade_task()`. Upstream already has low-level `docker.start(extra_mounts=...)`; it does not expose a task-scoped grader-artifact contract, and host grading happens after container teardown. Issue #2 remains the only relevant public design discussion.
- Rechecked public history: issue [#2](https://github.com/antgroup/Agent3Sigma-Canary/issues/2) is still open with 0 comments; PR [#1](https://github.com/antgroup/Agent3Sigma-Canary/pull/1) remains merged. No new desktop/UI duplicate, no maintainer response, and no PR authored by `UnknownGod2011` were found. No public action taken.
- Concrete private work: commit `8741bd632a636440a466f863040936f3535d051a` aligned the standalone desktop image with upstream's OpenClaw pin `2026.7.1-2` and `--ignore-scripts`. This was justified by the preceding `b38ef06` CI failures: smoke/reference builds stopped at npm 404 for `get-uri@8.0.2` while installing `openclaw@2026.4.11`; the upstream-builder compatibility workflow using the current pin passed. On `8741bd`, smoke and upstream compatibility passed, but the reference workflow failed only in its native OpenClaw CLI path: `GatewayCredentialsRequiredError` before a transcript was created. Its reference-controller bind-mount lifecycle still scored 1.0/1.0 twice, and the no-copyback negative control scored 0.0/1.0.
- Root cause traced to current upstream code, not guessed: `scripts/lib_docker.py` reads `ai.agentcanary.image_type`; `uses_native_openclaw()` returns true for `official*` image metadata; `scripts/lib_agent.py` adds `--local` only when that predicate is true and no persistent gateway is active. The standalone desktop Dockerfile lacked the official builder labels, so its custom image fell through to Gateway dispatch and demanded credentials. Upstream-built compatibility images carry the labels and used the embedded local path successfully.
- Corrective private commits: `47e703c696a1c6576b8b96011aaa5f302a3d58fe` attempted to add the labels but contained malformed escaped newlines; it was immediately superseded by `0806c95aeca9ed9d6c9839a68c6c62ff958e4892`, which re-read and corrected the Dockerfile to a valid single-line LABEL with `ai.agentcanary.image_type="official"` and `ai.agentcanary.openclaw_version="2026.7.1-2"`. No runtime/grader/upstream files were changed.
- Checks on latest corrected commit `0806c95` are still running at log time: [smoke run 43941389790](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43941389790) passed image build and reached real X11 / adapter checks; [reference run 43941389771](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43941389771) passed image build and reached moved-window OCR checks; [upstream compatibility run 43941389806](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43941389806) passed adapter regression tests and was preparing the upstream-builder image. No final result is claimed yet. Local Docker execution was unavailable.
- The baseline still proves deterministic real Tk/X11 observation/action and host grading with a reference controller; the local OpenClaw CLI path on the standalone image is awaiting revalidation after the metadata fix. The Gemini/live-model path remains opt-in and was not run; no autonomous visual-reasoning claim is justified. The fixture runs as root and is not a security isolation boundary.
- Unresolved: confirm all three `0806c95` workflows, maintainer preference for bounded export vs task-scoped artifact mount/lifecycle hook, and access to the durable Google Doc. The branch remains 19 commits behind upstream.
- Highest-value next step: inspect the three current workflow results; if the metadata correction restores the native `--local` OpenClaw path, preserve the evidence and avoid more speculative code. Wait for maintainer feedback on issue #2 before extracting any upstream-facing API; do not add security fault injection or open another public issue.

## Runner-version-skew correction — 2026-11-17 01:56 IST

- Rechecked repository refs: canonical upstream master `a03a36613feab18689d22b19243d8787d65f341d`, fork master `5072b78260d6dfe16f28a479ae83db4ef5c86bce`, and research branch `0e01b49043405d29eef70831ee32b3b604e058e3`. The research branch is 212 commits ahead of upstream and 19 behind; it is 212 ahead of fork master and 0 behind. The upstream/fork comparison contains 19 upstream commits since the fork point.
- Corrects the preceding 01:09 entry's root-cause attribution. The desktop Dockerfile now has official-image labels, but the **research-branch runner does not read them**: branch `scripts/lib_docker.py` only checks whether the image tag starts with `openclaw-official`, and branch `scripts/lib_agent.py` does not append OpenClaw's `--local` flag. Current upstream master has since added image-label detection and embedded local-agent dispatch. Therefore the labels alone could not fix the branch-local native CLI test.
- Exact CI evidence on implementation commit `0806c95aeca9ed9d6c9839a68c6c62ff958e4892`: [smoke run 43941389790](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43941389790) passed, including X11 GUI exercise and adapter checks; [reference lifecycle run 43941389771](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43941389771) passed its reference-controller/bind-mount positive path, but the branch-local native OpenClaw path failed before transcript creation with `GatewayCredentialsRequiredError`; [upstream compatibility run 43941389806](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43941389806) passed against exact upstream SHA `a03a36613feab18689d22b19243d8787d65f341d`. Its native OpenClaw local-provider runs (including the task-scoped bind mount) each scored 1.0/1.0 twice; the no-copyback negative control scored 0.0/1.0. This isolates the failure to the stale branch runner's invocation mode, not the GUI fixture, artifact handoff, or model provider.
- Private CI adjustment: removed the branch-local OpenClaw stub-image build and both native OpenClaw run steps from `desktop-reference-lifecycle.yml`. Those same local-provider and bind-mount paths are already exercised by `desktop-pr1-compatibility.yml` against current upstream master. The branch-local workflow remains responsible for the reference-controller lifecycle, task-scoped handoff, and no-copyback negative control. No benchmark runtime, task, grader, or upstream file was changed.
- Public state: issue [#2](https://github.com/antgroup/Agent3Sigma-Canary/issues/2) remains open with zero maintainer comments; upstream PR [#1](https://github.com/antgroup/Agent3Sigma-Canary/pull/1) remains merged. Its only review comment is a Copilot quota notice. No issue, comment, or PR was created by this run; no PR by `UnknownGod2011` was found.
- Scope and limitations: deterministic real Tk/X11 observation/action and AgentCanary grading are demonstrated. The local OpenClaw tool loop is demonstrated on current upstream, but not on the stale fork runner. The local provider is scripted/Tesseract-based, not autonomous visual reasoning or live-model evidence. The container runs as root and is not a security boundary. Local Docker execution is unavailable here; rely only on the cited CI results.
- Ledger access: the specified Google Doc could not be retrieved through Library search, and no Google Drive/Docs connector is available in this session. This public technical log is not a substitute for the inaccessible private ledger.
- Unresolved: whether to port the minimal current-upstream embedded-agent dispatch changes or rebase the research branch before any draft PR; maintainer preference on task-scoped artifact handoff; autonomous visual grounding; and agent/GUI isolation. Do not propose the branch wholesale while it is 19 commits behind.
- Highest-value next step: let the updated branch workflows run; keep the upstream-compatibility workflow as the source of truth for native OpenClaw execution. Wait for maintainer feedback on issue #2 before extracting a narrow upstream-facing artifact-handoff API. No security fault injection or second public issue.

## CI guard follow-up — 2026-11-17 02:02 IST

- The first CI push after separating branch-local reference tests from current-upstream OpenClaw tests exposed a stale assertion in `test_workflow_trigger_paths.py`: it still required the native OpenClaw bind-mount step to live in `desktop-reference-lifecycle.yml`. Both [smoke run 43950751386](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43950751386) and [reference run 43950751361](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43950751361) stopped at that assertion before Docker build or GUI execution; this was a test-contract mismatch, not a runtime failure.
- Updated the regression guard to require the native OpenClaw bind-mount experiment in `desktop-pr1-compatibility.yml`, where it runs against the fetched current upstream master, and to ensure the stale branch-local runner does not own that gate. The branch-local reference workflow still retains the reference-controller bind-mount, no-mount, and copyback controls.
- At log time, [compatibility run 43950751160](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43950751160) had passed the adapter regression suite and was building the current-upstream desktop image; its full lifecycle result was not yet available. No claim is made about the updated guard until it runs.
- No upstream public action. Issue #2 remains the sole design discussion and has no maintainer response.
