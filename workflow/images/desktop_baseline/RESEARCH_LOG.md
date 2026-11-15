# AgentCanary Desktop/UI Research Log

**Updated:** 2026-11-15  
**Research branch:** `research/desktop-ui-baseline`  
**Implementation revision:** `08ec169e39d8eff169882ecf52caaf7006c3cdf9`  
**Branch HEAD before this log update:** `44e72148004285e8ed34d8c24ff35c428669e3ba`  
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

The latest three workflows completed successfully on branch HEAD `44e72148004285e8ed34d8c24ff35c428669e3ba`:

- [Desktop reference lifecycle](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43732637371)
- [Desktop baseline smoke test](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43732637329)
- [Desktop compatibility against upstream master](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43732637326)

The reference-lifecycle workflow exercises repeated task-scoped bind-mount handoffs, repeated native OpenClaw CLI runs against a deterministic local provider, host-side grading, and a negative control. The upstream-compatibility workflow exercises the reference and local OpenClaw paths against the current upstream runner.

The local provider uses a scripted plan and Tesseract OCR. These runs validate screenshot-conditioned tool/runner integration and reproducibility, **not** autonomous visual reasoning or model quality. The optional live Gemini path is not claimed as passing evidence.

## Claim boundaries and limitations

- The OCR reference controller and local OpenClaw provider use deterministic Tesseract-based screenshot localization and a scripted plan. They validate integration and reproducibility, **not** autonomous visual reasoning or live-model quality.
- The experimental container is not a security boundary. The current setup does not establish OS-level isolation between an evaluated agent and the GUI state. Do not use it to claim resistance to a hostile agent.
- Security scenarios such as stale UI state, misleading confirmations, or partial execution remain future work after the baseline and trust boundary are reviewed.

## Upstream discussion status

- [Issue #2: Question: task-scoped artifact handoff for Docker-backed grading](https://github.com/antgroup/Agent3Sigma-Canary/issues/2) is open. It records the concrete handoff problem, the two prototype approaches, observed validation, explicit limitations, and asks maintainers for the preferred integration mechanism.
- The research branch is [available here](https://github.com/UnknownGod2011/Agent3Sigma-Canary/tree/research/desktop-ui-baseline) for implementation review.
- No pull request has been opened. The next step is to get architectural feedback on the artifact-handoff boundary and preferred integration shape before preparing a focused draft PR.
