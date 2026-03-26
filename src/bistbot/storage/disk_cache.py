from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.bars_dir = self.root_dir / "bars"
        self.bars_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_state_path = self.root_dir / "runtime_state.json"
        self.research_state_path = self.root_dir / "research_state.json"

    def load_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def save_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def bar_cache_path(self, symbol: str, timeframe: str) -> Path:
        return self.bars_dir / timeframe / f"{symbol.upper()}.json"

    def load_runtime_state(self) -> dict[str, Any] | None:
        return self.load_json(self.runtime_state_path)

    def save_runtime_state(self, payload: dict[str, Any]) -> None:
        self.save_json(self.runtime_state_path, payload)

    def load_research_state(self) -> dict[str, Any] | None:
        return self.load_json(self.research_state_path)

    def save_research_state(self, payload: dict[str, Any]) -> None:
        self.save_json(self.research_state_path, payload)
