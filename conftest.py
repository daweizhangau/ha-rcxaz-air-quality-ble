"""Root conftest — registers the --live flag and auto-skips live tests."""
from __future__ import annotations

import logging
import sys

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live BLE hardware tests (requires the physical RCXAZ Air Quality Detector).",
    )
    parser.addoption(
        "--device-address",
        action="store",
        default=None,
        help="BLE MAC address of the device (for live tests).",
    )
    parser.addoption(
        "--device-name",
        action="store",
        default=None,
        help="BLE device name, e.g. XS-1234 (for live tests).",
    )
    parser.addoption(
        "--auto",
        action="store_true",
        default=False,
        help="Auto-discover a device with 'XS' in name (for live tests).",
    )
    parser.addoption(
        "--duration",
        action="store",
        default=30,
        type=int,
        help="Test duration in seconds (default: 30).",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Add console logging when --live is active (so logs show without -s)."""
    if config.getoption("--live", default=False):
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)8s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--live"):
        return  # Run everything — user opted in

    skip_live = pytest.mark.skip(
        reason="Live BLE test skipped — run with: pytest -m live --live"
    )
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip_live)
