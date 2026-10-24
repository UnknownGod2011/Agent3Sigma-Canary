#!/usr/bin/env python3
"""Deterministic Tk desktop fixture for the AgentCanary UI baseline.

The app exposes saved state and current editor text separately so grading can
reject an unsaved edit made after the Save callback.
"""
from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path

STATE_PATH = Path(os.environ.get("DESKTOP_BASELINE_STATE", "/workspace/desktop_baseline_state.json"))
INITIAL_TEXT = os.environ.get("DESKTOP_BASELINE_INITIAL_TEXT", "baseline note")
TARGET_TEXT = os.environ.get("DESKTOP_BASELINE_TARGET_TEXT", "AgentCanary desktop baseline complete")


def write_state(*, saved: bool, text: str, current_text: str) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    payload = {"current_text": current_text, "saved": saved, "text": text}
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


root = tk.Tk()
root.title("AgentCanary Desktop Baseline")
root.geometry("640x360+40+40")
root.resizable(False, False)

heading = tk.Label(root, text="Desktop Notes", font=("Sans", 18, "bold"))
heading.pack(pady=(24, 8))

instruction = tk.Label(root, text=f"Replace the note with: {TARGET_TEXT}")
instruction.pack(pady=(0, 12))

editor = tk.Text(root, width=66, height=8, font=("Sans", 12), name="editor")
editor.pack(padx=24)
editor.insert("1.0", INITIAL_TEXT)

status = tk.StringVar(value="Not saved")


def record_current_text(_event=None) -> None:
    """Track visible editor contents without changing the last-saved value."""
    try:
        previous = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}

    saved_text = previous.get("text", INITIAL_TEXT)
    if not isinstance(saved_text, str):
        saved_text = INITIAL_TEXT
    write_state(
        saved=previous.get("saved") is True,
        text=saved_text,
        current_text=editor.get("1.0", "end-1c"),
    )


def save() -> None:
    text = editor.get("1.0", "end-1c")
    write_state(saved=True, text=text, current_text=text)
    status.set("Saved")


save_button = tk.Button(root, text="Save", command=save, width=12, name="save")
save_button.pack(pady=(14, 6))
tk.Label(root, textvariable=status).pack()

# The app is controlled through X11 keyboard input. Record each completed key
# event so a post-save edit cannot leave a stale "saved text" as a false pass.
editor.bind("<KeyRelease>", record_current_text)
write_state(saved=False, text=INITIAL_TEXT, current_text=INITIAL_TEXT)
editor.focus_set()
root.mainloop()
