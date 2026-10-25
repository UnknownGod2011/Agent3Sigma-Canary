# Desktop UI baseline (experimental)

This experimental research image tests one question only: can AgentCanary's existing
runner evaluate an agent that must observe and act on a genuine desktop GUI?
It intentionally contains **no security fault injection**.

## What is different from `official`

The image preserves the official OpenClaw + mock-api runner contract and adds:

- Xvfb virtual X11 display (`:99`)
- a deterministic Tk notes application
- `desktopctl observe` for PNG screenshots
- `desktopctl click`, `type`, and `key` for mouse/keyboard input
- a machine-checkable state artifact at `/tmp/agentcanary-desktop/desktop_baseline_state.json`, outside the agent workspace during interaction; the harness copies it into the host-side grading workspace only after execution

## Scope and isolation limitation

This is a desktop-integration feasibility fixture, not a security boundary. The current Docker image does not set a non-root `USER`, and AgentCanary's Docker adapter invokes `docker exec` without a user override. Consequently, the evaluated OpenClaw process and Tk fixture run as the container's default root user, so placing the state JSON outside the agent workspace does **not** make it OS-inaccessible to the agent. The grader rejects unapproved commands and non-PNG reads in the recorded transcript and independently checks persisted state; those checks demonstrate a constrained baseline path, not OS-level isolation or resistance to a hostile agent with unrestricted runtime access.

Do not interpret the state path as confidential or use this setup for security-robustness claims. Before adversarial desktop/security experiments, establish a genuine agent–GUI isolation boundary or explicitly redesign the trust model.

The target text defaults to `AgentCanary desktop baseline complete`. The app
starts with a different value and writes `saved: false`; only the GUI Save
button changes the saved text and sets `saved: true`. Keyboard events also
update `current_text`, allowing the grader to reject a later unsaved edit.

## Build the research image

From the repository root, after `bash setup.sh` has generated the official
OpenClaw configuration:

```bash
workdir="$(mktemp -d)"
bash workflow/images/desktop_baseline/prepare.sh "$workdir" "" "$PWD"
docker build -t openclaw-desktop-baseline "$workdir"
```

This is deliberately not added to the normal interactive image-builder menu
until the experiment proves useful.

## Minimal manual validation

Start the image using the same environment/configuration assumptions as the
normal AgentCanary runner, then inside the container:

```bash
desktopctl start
desktopctl observe /tmp/before.png
# Interact only through desktopctl mouse/keyboard commands.
desktopctl key ctrl+a
desktopctl type "AgentCanary desktop baseline complete"
# Click Save after locating it from the screenshot.
desktopctl observe /tmp/after.png
cat /tmp/agentcanary-desktop/desktop_baseline_state.json
```

The final `cat` is for maintainer-side inspection only; it must not be part of
the evaluated agent trajectory.

A valid baseline run must show all of the following:

1. the evaluated agent obtains GUI state from a screenshot rather than reading
   the backing JSON state;
2. the state transition is caused by mouse/keyboard interaction with the GUI;
3. the AgentCanary transcript records the interaction tool calls;
4. final grading checks the persisted state independently of the agent report;
5. repeated runs start from the same known initial state.

A CLI-only state mutation does not count as desktop feasibility.
