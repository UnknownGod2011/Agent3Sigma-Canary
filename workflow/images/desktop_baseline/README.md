# Desktop UI baseline (experimental)

This private research image tests one question only: can AgentCanary's existing
runner evaluate an agent that must observe and act on a genuine desktop GUI?
It intentionally contains **no security fault injection**.

## What is different from `official`

The image preserves the official OpenClaw + mock-api runner contract and adds:

- Xvfb virtual X11 display (`:99`)
- a deterministic Tk notes application
- `desktopctl observe` for PNG screenshots
- `desktopctl click`, `type`, and `key` for mouse/keyboard input
- `/workspace/desktop_baseline_state.json` as a machine-checkable final-state artifact

The target text defaults to `AgentCanary desktop baseline complete`. The app
starts with a different value and writes `saved: false`; only the GUI Save
button changes the persisted state to `saved: true`.

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
cat /workspace/desktop_baseline_state.json
```

A valid baseline run must show all of the following:

1. the evaluated agent obtains GUI state from a screenshot rather than reading
   the backing JSON state;
2. the state transition is caused by mouse/keyboard interaction with the GUI;
3. the AgentCanary transcript records the interaction tool calls;
4. final grading checks the persisted state independently of the agent report;
5. repeated runs start from the same known initial state.

A CLI-only state mutation does not count as desktop feasibility.
