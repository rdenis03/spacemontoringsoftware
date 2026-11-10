from datetime import datetime, timezone
from pathlib import Path

import pytest

from orbit.core import Pipeline, Store, create, load_settings

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "orbit.toml"
DAY_89 = datetime(2027, 4, 2, 10, tzinfo=timezone.utc)
DAY_90 = datetime(2027, 4, 3, 10, tzinfo=timezone.utc)


@pytest.fixture
def settings():
    return load_settings(CONFIG)


@pytest.fixture
def loaded_pipeline(settings):
    """Pipeline on an in-memory database with the example data ingested (not yet run)."""
    pipeline = Pipeline.from_settings(settings, store=Store(":memory:"))
    for choice in settings.sources:
        pipeline.ingest(create("source", choice.use, **choice.options))
    return pipeline


@pytest.fixture
def ran_pipeline(loaded_pipeline):
    loaded_pipeline.run()
    return loaded_pipeline
