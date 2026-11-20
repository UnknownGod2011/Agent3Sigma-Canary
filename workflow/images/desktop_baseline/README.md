# Desktop UI baseline (experimental)

This experimental research image tests one question only: can AgentCanary's existing
runner evaluate an agent that must observe and act on a genuine desktop GUI?
It intentionally contains **no security fault injection**.

## What is different from `official`

The image preserves the official OpenClaw + mock-api runner contract and adds:

- Xvfb virtual X11 display (`:99`)
- a deterministic Tk notes application
- `desktopctl observe` for PNG screenshots; reusing a screenshot path refreshes that exact file
- `desktopctl click`, `type`, and `key` for mouse/keyboard input
- a machine-checkable state artifact at `/tmp/agentcanary-desktop/desktop_baseline_state.json`; the original reference adapter exports it with a bounded `docker exec` read before teardown, while a separate CI path validates a task-scoped host bind mount and copies the validated artifact into the host-side grading workspace
- bounded transcript export of regular `sessions/*.jsonl` files through `docker exec`; the experimental adapter does not use container-to-host `docker cp` or tar extraction

## Scope and process boundary

The runner still uses its default root `docker exec` path for task setup, container lifecycle, and host-side artifact export. The desktop image adds a task-specific `/usr/local/bin/openclaw` shim: it launches the actual OpenClaw CLI and its child tool processes as the unprivileged `node` user, with `HOME=/home/node`. A compatibility symlink at `/root/.openclaw` preserves the runner's existing cleanup path; the task-scoped safe transcript exporter reads the real node-home directory directly. The Tk fixture and Xvfb run as root; `desktopctl start` keeps the grader-state directory at mode `0700`, keeps fixture source at mode `0600`, and grants X11 access only to local user `node`. The agent writes screenshots to a separate node-owned runtime directory. GUI actions fail if the OpenClaw shim's non-root requirement is not met.

This is a process-level agent/fixture separation inside one container, not a hardened container sandbox or a general security guarantee. The host runner and container root retain access to the fixture and grader artifact; the agent still has X11 access and can run arbitrary commands as `node`. The setup does not claim resistance to X-server vulnerabilities, container escape, or a compromised Docker daemon. No security fault injection is included.

Do not interpret the grader-state file as confidential from the host runner or container root, and do not use this baseline for broad security-robustness claims. The current milestone is limited to demonstrating that a non-root OpenClaw agent can observe and act through the real GUI while the grader's backing state and fixture source remain unreadable under the container's Unix permission model.

The target text defaults to `AgentCanary desktop baseline complete`. The app
starts with a different value and writes `saved: false`; every actual GUI Save
callback increments `save_count`, and both the grader and reference runner
require exactly one callback. Keyboard events also update `current_text`,
allowing the grader to reject a later unsaved edit or a premature save followed
by a correct final save.

## Screenshot-grounded reference controller

The credential-free reference controller uses Tesseract OCR on the initial
screenshot to locate the visible `baseline note` text, then uses a second
screenshot to locate the `Save` button after editing. When the instruction also
contains the word “save”, the button is disambiguated by its centered position
above the visible `Not saved` status label. Both click positions are derived
from OCR bounding boxes; missing or ambiguous text fails closed. The fixture start command also waits for the initial Tk paint to settle before the first observation.

The task's normal setup moves the Notes window from its fixture default at
`+40+40` to `+140+120`, and the runtime preflight verifies that origin. The
reference controller and local OpenClaw provider must derive their clicks from
the delivered screenshots rather than relying on the default coordinates. A
separate Xvfb layout probe also completed the task at both origins, with the
derived editor and Save-button coordinates moving with the window. This is
deterministic OCR-based reference behavior, not autonomous visual reasoning or
model-quality evidence.

## Deterministic OpenClaw tool-loop integration

CI also runs the task through the unmodified OpenClaw CLI against a credential-free,
local OpenAI-compatible provider. The provider emits a scripted sequence of normal
tool calls. For both clicks, it decodes the screenshot attached to the matching
`read` result and uses the same deterministic Tesseract OCR localizer as the
reference controller to choose the editor and Save-button coordinates. Before
Save, it also requires the exact target text to be visible in a post-edit
screenshot; it requests up to two additional observe/read cycles and refuses to
save if the text remains incomplete. The ordinary AgentCanary transcript and
independent task grader must still validate the saved GUI state.

This is screenshot-conditioned deterministic control, not autonomous visual
reasoning or model-quality evidence: the local provider follows a scripted plan
and uses OCR rather than learned visual reasoning. It complements the reference
controller by testing the real OpenClaw tool dispatch/provider/transcript path
without API credentials, external model-provider calls, or per-run API cost.
It does not change the documented container isolation limitation.

## Task-scoped artifact handoff comparison

The CI workflow compares the existing pre-teardown export with a task-scoped
bind mount at `/tmp/agentcanary-desktop`. The mount is a fresh host temporary
directory for each run. After the container stops, the adapter accepts only a
bounded, regular, single-link state file and writes it into the task's host
workspace before the existing `grade_task` call.

The comparison covers two repeated OCR-reference runs and two repeated native
OpenClaw CLI runs against the deterministic local provider, all using the bind
mount. Each positive run scored 1.0/1.0. For each repeated pair, CI compares the
raw final-state bytes, ordered state-changing GUI-action sequence, and captured
screenshot payloads by SHA-256. It writes a machine-readable
`desktop_reproducibility_manifest.json` into the first run's retained artifact;
the manifest records the upstream commit, per-run hashes, action/observation/
read counts, and bounded verification retries. Observation/retry counts may
differ by up to two bounded re-observations while the Tk event loop processes
typed input. The no-mount and no-copyback controls recorded the GUI tool
trajectory but scored 0.0/1.0 because the host grader could not see the state
artifact.

This is a fork-only lifecycle wrapper, not a first-class AgentCanary API. The
bind mount is writable and visible to container root; it is an artifact-handoff
experiment, not a secure evidence channel or isolation boundary. The local
provider is scripted, so these results do not establish autonomous model quality
or semantic screenshot understanding.

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
the evaluated agent trajectory. Host-side artifact collection uses bounded
`docker exec` reads and never extracts an agent-controlled container archive.

A valid baseline run must show all of the following:

1. a valid 800x600 X11 screenshot is delivered to the evaluated agent through
   the normal image-bearing `read` tool before GUI input;
2. the state transition is caused by mouse/keyboard interaction with the GUI;
3. the AgentCanary transcript records the interaction tool calls;
4. final grading checks the persisted state independently of the agent report;
5. repeated runs start from the same known initial state.

A CLI-only state mutation does not count as desktop feasibility. These transcript
checks establish screenshot delivery and ordering, not semantic visual understanding.
The reference controller and local OpenClaw stub use Tesseract OCR to derive
coordinates from screenshots; autonomous model visual grounding remains unvalidated.
