#!/usr/bin/env python3
"""Deterministic Tk desktop fixture for the AgentCanary UI baseline.

The app intentionally exposes success only through GUI interaction. The saved
state is machine-readable so AgentCanary grading can verify the final state
without relying on the agent's own report.
"""
from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path

STATE_PATH = Path(os.environ.get("DESKTOP_BASELINE_STATE", "/workspace/desktop_baseline_state.json"))
INITIAL_TEXT = os.environ.get("DESKTOP_BASELINE_INITIAL_TEXT", "baseline note")
TARGET_TEXT = os.environ.get("DESKTOP_BASELINE_TARGET_TEXT", "AgentCanary desktop baseline complete")


def write_state(*, saved: bool, text: str) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps({"saved": saved, "text": text}, sort_keys=True) + "\n", encoding="utf-8")
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


def save() -> None:
    text = editor.get("1.0", "end-1c")
    write_state(saved=True, text=text)
    status.set("Saved")


save_button = tk.Button(root, text="Save", command=save, width=12, name="save")
save_button.pack(pady=(14, 6))
tk.Label(root, textvariable=status).pack()

write_state(saved=False, text=INITIAL_TEXT)
editor.focus_set()
root.mainloop()
