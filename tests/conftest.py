"""
Shared pytest fixtures.

pytest-asyncio is configured in asyncio_mode="auto" so every async test
function is automatically treated as a coroutine test without needing
the @pytest.mark.asyncio decorator on each one.
"""

import pytest

# ---------------------------------------------------------------------------
# Global asyncio mode for pytest-asyncio
# ---------------------------------------------------------------------------
# Equivalent to adding asyncio_mode = "auto" in pytest.ini / pyproject.toml.
# Declared here so no extra config file is needed.

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )