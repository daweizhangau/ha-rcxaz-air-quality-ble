"""Constants for the RCXAZ Air Quality Detector integration."""

DOMAIN = "rcxaz_air_quality"

# BLE GATT characteristic UUIDs (service 0000c760-...)
C760_SERVICE_UUID = "0000c760-0000-1000-8000-00805f9b34fb"
C761_NOTIFY_UUID  = "0000c761-0000-1000-8000-00805f9b34fb"  # Notify / read
C762_WRITE_UUID   = "0000c762-0000-1000-8000-00805f9b34fb"  # Write-without-response

# BLE handles (for reference — not used in production, using UUIDs instead)
NOTIFY_HANDLE = 0x000B
WRITE_HANDLE  = 0x0009

# Clock sync interval: re-sync device clock every hour (seconds)
CLOCK_SYNC_INTERVAL = 3600

# Entity unique-ID suffixes
SUFFIX_TEMPERATURE      = "temperature"
SUFFIX_HUMIDITY         = "humidity"
SUFFIX_CO2              = "co2"
SUFFIX_TVOC             = "tvoc"
SUFFIX_HCHO             = "hcho"
SUFFIX_PM1_0            = "pm1_0"
SUFFIX_PM2_5            = "pm2_5"
SUFFIX_PM10             = "pm10"
SUFFIX_CONNECTION_STATUS = "connection_status"
SUFFIX_RSSI             = "rssi"
SUFFIX_LAST_SEEN        = "last_seen"

# Connection status values
CONN_STATUS_CONNECTED    = "Connected"
CONN_STATUS_CONNECTING   = "Connecting"
CONN_STATUS_DISCONNECTED = "Disconnected"
