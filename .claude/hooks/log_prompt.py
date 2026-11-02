"""UserPromptSubmit hook: append each prompt verbatim to PROMPTS.md."""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Context blocks injected by the IDE extension, not typed by the user.
IDE_CONTEXT = re.compile(r"<(ide_opened_file|ide_selection)>.*?</\1>\s*", re.DOTALL)

payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
prompt = IDE_CONTEXT.sub("", payload.get("prompt", ""))
if not prompt.strip():
    sys.exit(0)

project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
log_file = project_dir / "PROMPTS.md"

timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
entry = f"## {timestamp}\n\n{prompt.rstrip()}\n\n---\n\n"

with log_file.open("a", encoding="utf-8", newline="\n") as f:
    f.write(entry)
