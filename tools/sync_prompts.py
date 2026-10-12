"""Copy the master and six runtime prompts from Instructions.md into backend/app/prompts/ (Req 1.8)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.llm import PROMPT_FILES, extract_instruction_prompts  # noqa: E402


def main() -> int:
    prompts = extract_instruction_prompts((ROOT / "Instructions.md").read_text(encoding="utf-8"))
    missing = [p for p in PROMPT_FILES if p not in prompts]
    if missing:
        print("Missing prompt blocks in Instructions.md:", ", ".join(missing))
        return 1
    out = ROOT / "backend" / "app" / "prompts"
    out.mkdir(parents=True, exist_ok=True)
    for pid, name in PROMPT_FILES.items():
        p = prompts[pid]
        (out / name).write_text(f"version: {p.version}\n---\n{p.text}\n", encoding="utf-8", newline="\n")
        print(f"wrote {name} ({p.version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
