"""
State management – load / save / reset pipeline_state.json.

Design decisions:
- Write to a temp file then rename (atomic write) so a crash mid-save never
  corrupts the state file.
- State is a plain Pydantic model serialised to JSON; no DB dependency.
- Each stage checks its completion flag before executing, enabling safe resume.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from models.schemas import PipelineState
from core.config import get_config
from core.logger import get_logger

logger = get_logger(__name__)


def _state_path() -> Path:
    return Path(get_config().STATE_FILE)


def load_state(domain: str) -> PipelineState:
    """
    Load state from disk if it exists AND matches the seed domain.
    Otherwise, return a fresh PipelineState for the given domain.
    """
    path = _state_path()
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            state = PipelineState.model_validate(data)
            if state.seed_domain == domain:
                logger.info("Resuming pipeline from cached state: %s", path)
                return state
            else:
                logger.warning(
                    "Cached state domain '%s' != requested '%s'. Starting fresh.",
                    state.seed_domain,
                    domain,
                )
        except Exception as exc:
            logger.warning("Failed to load state file (%s). Starting fresh. Error: %s", path, exc)

    logger.info("Initialising new pipeline state for domain: %s", domain)
    return PipelineState(seed_domain=domain)


def save_state(state: PipelineState) -> None:
    """Atomically persist state to disk."""
    state.last_updated = datetime.utcnow()
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = state.model_dump_json(indent=2)

    # Atomic write: write to temp → rename
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=".pipeline_state_tmp_", suffix=".json"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, path)
        logger.debug("State saved to %s", path)
    except Exception as exc:
        logger.error("Failed to save state: %s", exc)
        raise


def reset_state(domain: str) -> PipelineState:
    """Delete existing state and return a fresh one."""
    path = _state_path()
    if path.exists():
        path.unlink()
        logger.info("State file deleted: %s", path)
    return PipelineState(seed_domain=domain)