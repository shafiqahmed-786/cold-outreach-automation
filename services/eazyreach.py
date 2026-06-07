"""
EazyReach has been removed from this pipeline.

EazyReach was Stage 3 (LinkedIn URL → verified work email).
Its functionality has been absorbed into Stage 2 (Prospeo), which now
uses the Search Person + Bulk Enrich Person endpoints to return both
decision-maker profiles and verified emails in a single stage.

This file is retained as a tombstone so that any import of EazyreachService
raises an ImportError with a clear message rather than an AttributeError
from a missing symbol.
"""

raise ImportError(
    "EazyreachService has been removed. "
    "Email enrichment is now handled by ProspeoService (services/prospeo.py). "
    "See pipeline/orchestrator.py for the updated 3-stage pipeline."
)