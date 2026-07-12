# Development

This document is for contributors and developers. For user installation instructions see [README.md](README.md).

---

## Repository layout

| Path | Purpose |
|------|---------|
| `custom_components/rcxaz_air_quality/` | The HACS component — install this in HA |
| `tests/` | Unit tests (BLE fully mocked — no hardware needed) |
| `img/` | Device images |
| `.github/workflows/` | CI — runs unit tests on every push / PR |

Key source files in `custom_components/rcxaz_air_quality/`:

| File | Purpose |
|------|---------|
| `protocol.py` | Pure-Python frame parser and command builder (no HA/BLE deps) |
| `ha_client.py` | BLE connection lifecycle (connect, subscribe, notification handler) |
| `coordinator.py` | HA `DataUpdateCoordinator` wrapper; notification-driven data flow |
| `sensor.py` | Sensor entity definitions |
| `config_flow.py` | Bluetooth auto-discovery and manual config flow |
| `const.py` | Constants, UUIDs, entity suffixes |
| `diagnostics.py` | Diagnostics support |

---

## Setting up the test environment

Requires [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda.

```bash
# Create and activate the conda environment
conda env create -f environment_ha.yml
conda activate ha-rcxaz-air-quality-ble

# Run all unit tests (no hardware required — BLE is fully mocked)
pytest tests/ -v
```

The CI workflow (`.github/workflows/tests.yml`) runs the same command on every push and pull request.

---

## Protocol notes

The RCXAZ Air Quality Detector communicates over BLE GATT:

| UUID | Role |
|---|---|
| `0000c760-...` | Primary service |
| `0000c761-...` | **Notify** — receive sensor data frames |
| `0000c762-...` | **Write** — send activation byte and datetime sync |

### Activation sequence

1. Subscribe to notifications on C761
2. Write `0x1E` to C762 → sensor data starts flowing at ~1 Hz
3. Write datetime sync frame (page 0x0106) to C762 → sets device clock
4. Clock is re-synced every hour

### Frame format

| Offset | Size | Description |
|---|---|---|
| 0 | 1 | Prefix byte: always `0x23` |
| 1 | 1 | Payload length (N) |
| 2 | 2 | Page ID (big-endian) |
| 4 | N-2 | Payload data |
| 2+N | 1 | Checksum: `(sum(body) & 0xFF) ^ 0xFF` |

### Data pages

| Page ID | Payload | Fields |
|---|---|---|
| `0x1003` | 2+ bytes | Timestamp / counter |
| `0x1004` | 4 bytes | Temperature (°C ÷10), Humidity (%) |
| `0x1004` | 6 bytes | CO₂ (ppm), TVOC (mg/m³ ÷1000), HCHO (mg/m³ ÷1000) |
| `0x1007` | 6 bytes | PM1.0, PM2.5, PM10 (µg/m³) |
| `0x0401` | 3+ bytes | Acknowledgment |

### Command frames

| Page ID | Purpose |
|---|---|
| `0x0106` | Set date/time (BCD-encoded) |
| `0x1E` (single byte) | Activate data stream |

---

## Live hardware tests

Live tests connect directly to the physical device via the system Bluetooth stack. These are excluded from normal runs and CI — opt in explicitly:

```bash
conda activate ha-rcxaz-air-quality-ble

# Requires the detector to be powered on with Bluetooth enabled
pytest -m live --live -v
```

On macOS you may be prompted for Bluetooth permission — grant it under **System Settings → Privacy & Security → Bluetooth**.
