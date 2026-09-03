"""Provider-neutral, auditable continuation checkpoint primitives."""

from .model import Checkpoint, CheckpointSnapshot

__all__ = ["Checkpoint", "CheckpointSnapshot"]
