# AgentCanary Desktop/UI Research Log

**Updated:** 2026-11-15  
**Research branch:** `research/desktop-ui-baseline`  
**Branch HEAD:** `08ec169e39d8eff169882ecf52caaf7006c3cdf9`  
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

The current question for upstream maintainers is whether AgentCanary should expose a general, opt-in task-scoped artifact-handoff mechanism for outputs needed by post-run grading, and which lifecycle/interface is preferred. This is a design question, not a claim that the existing runner is broken.

## Validation status

At branch HEAD `08ec169e39d8eff169882ecf52caaf7006c3cdf9`, these GitHub Actions workflows completed successfully:

- [Desktop reference lifecycle](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43706199131)
- [Desktop baseline smoke test](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43706199209)
- [Desktop compatibility against current upstream master](https://github.com/UnknownGod2011/Agent3Sigma-Canary/actions/runs/43706199344)

The reference-lifecycle workflow exercises repeated task-scoped bind-mount handoffs, repeated native OpenClaw CLI runs against a deterministic local provider, host-side grading, and a negative control. The upstream-compatibility workflow repeats the reference and local OpenClaw paths against the current upstream runner.

## Claim boundaries and limitations

- The OCR reference controller and local OpenClaw provider use deterministic Tesseract-based screenshot localization and a scripted plan. They validate screenshot-conditioned tool/runner integration and reproducibility, **not** autonomous visual reasoning or model quality.
- The latest smoke workflow skipped the optional live Gemini job; no live-model success is claimed by these results.
- The experimental container is not a security boundary. The current setup does not establish OS-level isolation between an evaluated agent and the GUI state. Do not use it to claim resistance to a hostile agent.
- Security scenarios such as stale UI state, misleading confirmations, or partial execution remain future work after the baseline and trust boundary are reviewed.

## Upstream discussion status

No upstream issue or pull request has been created by this research work as of this update. The intended next public discussion is one focused issue about task-scoped artifact handoff for Docker-backed evaluations—not a broad request for generic desktop support.

After maintainer feedback, the next step is to share or open a draft PR for the validated research implementation, following the maintainers' preferred integration direction.
