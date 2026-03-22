#!/usr/bin/env python3
"""
Thin wrapper so you can run from the `infra/` directory:

  cd infra
  python scripts/dlq_redrive.py stats --dlq-url "$DLQ_URL"

The real implementation lives at repo root: ../../scripts/dlq_redrive.py
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGET = _REPO_ROOT / "scripts" / "dlq_redrive.py"

if not _TARGET.is_file():
    print(f"Expected script at {_TARGET}", file=sys.stderr)
    sys.exit(1)

runpy.run_path(str(_TARGET), run_name="__main__")
