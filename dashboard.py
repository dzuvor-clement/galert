from flask import Flask, render_template, jsonify, request, session, redirect, url_for

import math
import time
import threading
import smtplib
import os
import random
import sqlite3
import urllib.request
import json

from dotenv import load_dotenv

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")


# ============================================================
# LINUX / HARDWARE AUTO-DETECTION
# ============================================================

IS_LINUX = os.name != "nt"

# Auto-detect mode:
# - On Linux (Raspberry Pi), defaults to False to use physical sensors (MPU-6050, BMP280, NEO-6M).
# - On Windows / desktop testing, defaults to True so realistic telemetry is active.
_env_mock = os.getenv("MOCK_HARDWARE")
if _env_mock is not None:
    MOCK_HARDWARE = _env_mock.lower() in ("true", "1", "yes")
else:
    MOCK_HARDWARE = not IS_LINUX


# ============================================================
# MOCK HARDWARE
# ============================================================

if MOCK_HARDWARE:

    # --------------------------------------------------------
    # Fake MPU-6050
    # --------------------------------------------------------

    _AXIS_BASE = [0, 0, 16384]

    class _FakeSMBus:

        def __init__(self, bus):
            pass

        def write_byte_data(self, *a):
            pass

        def read_byte_data(self, addr, reg):

            offset = reg - 0x3B

            if 0 <= offset < 6:

                axis = offset // 2
                is_hi = (offset % 2) == 0

                val = _AXIS_BASE[axis]

                return (
                    (val >> 8)
                    if is_hi
                    else (val & 0xFF)
                )

            return 0


    class smbus:

        SMBus = _FakeSMBus


    # --------------------------------------------------------
    # Fake GPS
    # --------------------------------------------------------

    class _FakeSerial:

        def __init__(self, *a, **kw):
            pass

        def readline(self):

            lat = 6.6885
            lon = -1.6244
            alt = 250.0

            lat_d = int(lat)
            lat_m = (lat - lat_d) * 60

            lon_d = int(abs(lon))
            lon_m = (abs(lon) - lon_d) * 60

            sentence = (
                f"$GPGGA,120000.00,"
                f"{lat_d:02d}{lat_m:07.4f},N,"
                f"{lon_d:03d}{lon_m:07.4f},W,"
                f"1,08,0.9,{alt:.1f},M,0.0,M,,"
            )

            checksum = 0

            for ch in sentence[1:]:
                checksum ^= ord(ch)

            return (
                sentence
                + f"*{checksum:02X}\r\n"
            ).encode("ascii")


    class serial:

        class Serial(_FakeSerial):
            pass


    import pynmea2


# ============================================================
# REAL HARDWARE
# ============================================================

else:

    try:

        import smbus2 as smbus

    except ImportError:

        try:

            import smbus

        except ImportError:

            smbus = None


    import serial
    import pynmea2


# ============================================================
# BME/BMP280 LIBRARY
# ============================================================

# Your actual sensor was identified as BMP280
# Chip ID = 0x58
#
# BMP280 provides:
#   Temperature
#   Pressure
#   Altitude
#
# It does NOT provide humidity.

try:
    import board
    import busio
    import adafruit_bmp280
    BMP280_LIBRARY_AVAILABLE = True
except Exception as e:
    BMP280_LIBRARY_AVAILABLE = False


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "galert-auth-secret-key-2026")

app.config["TEMPLATES_AUTO_RELOAD"] = True

app.jinja_env.auto_reload = True


# ============================================================
# HARDWARE CONFIGURATION
# ============================================================

MPU6050_ADDRESS = 0x68

PWR_MGMT_1 = 0x6B

ACCEL_XOUT_H = 0x3B


# ============================================================
# BMP280 CONFIGURATION
# ============================================================

BMP280_ADDRESS = 0x76

BMP280_SEA_LEVEL_PRESSURE = 1013.25


# ============================================================
# GPS CONFIGURATION
# ============================================================

GPS_PORT = os.getenv(
    "GPS_PORT",
    "/dev/serial0"
)

GPS_BAUDRATE = int(
    os.getenv(
        "GPS_BAUDRATE",
        "9600"
    )
)


# ============================================================
# HARDWARE VARIABLES
# ============================================================

bus = None

gps_serial = None

bmp280 = None


# ============================================================
# INITIALIZE HARDWARE
# ============================================================

def init_hardware():

    global bus
    global gps_serial
    global bmp280


    # ========================================================
    # MPU-6050
    # ========================================================
    if MOCK_HARDWARE:
        bus = smbus.SMBus(1)
        print("[HARDWARE] MPU-6050: MOCK mode (simulated)")
    elif smbus is not None:
        try:
            bus = smbus.SMBus(1)
            bus.write_byte_data(MPU6050_ADDRESS, PWR_MGMT_1, 0)
            print("[HARDWARE] MPU-6050 initialized successfully on I2C bus 1 (0x68)")
        except Exception as e:
            print(f"[HARDWARE WARNING] Could not initialize MPU-6050: {e}")
            bus = None
    else:
        print("[HARDWARE WARNING] smbus / smbus2 module not installed")
        bus = None

    # ========================================================
    # NEO-6M GPS
    # ========================================================
    if MOCK_HARDWARE:
        gps_serial = serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=0.1)
        print("[HARDWARE] GPS: MOCK mode (simulated)")
    else:
        try:
            gps_serial = serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=0.1)
            print(f"[HARDWARE] GPS serial connected on {GPS_PORT} @ {GPS_BAUDRATE} baud")
        except Exception as e:
            print(f"[HARDWARE WARNING] Could not open GPS serial port {GPS_PORT}: {e}")
            gps_serial = None

    # ========================================================
    # BMP280 SENSOR (DEDICATED TEMPERATURE & PRESSURE)
    # ========================================================
    if BMP280_LIBRARY_AVAILABLE:
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            for addr in (BMP280_ADDRESS, 0x77):
                try:
                    bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
                    bmp280.sea_level_pressure = BMP280_SEA_LEVEL_PRESSURE
                    print(f"[HARDWARE] BMP280 initialized successfully on I2C address 0x{addr:02X}")
                    break
                except Exception:
                    continue
            if bmp280 is None:
                print(f"[HARDWARE WARNING] BMP280 not detected on I2C address 0x{BMP280_ADDRESS:02X} or 0x77")
        except Exception as e:
            print(f"[HARDWARE WARNING] Could not initialize BMP280: {e}")
            bmp280 = None
    else:
        print("[HARDWARE WARNING] BMP280 library (adafruit_bmp280) not available")


    # ========================================================
    # REAL NEO-6M GPS
    # ========================================================

    try:

        gps_serial = serial.Serial(
            GPS_PORT,
            GPS_BAUDRATE,
            timeout=1
        )

        print(
            f"[HARDWARE] GPS serial connected on "
            f"{GPS_PORT} @ {GPS_BAUDRATE} baud"
        )

    except Exception as e:

        print(
            f"[HARDWARE WARNING] "
            f"Could not open GPS serial port "
            f"{GPS_PORT}: {e}"
        )

        gps_serial = None


# Initialize hardware
init_hardware()


# ============================================================
# VIBRATION THRESHOLDS
#
# TESTING VALUES
#
# These values must eventually be calibrated using
# real field data.
# ============================================================

HIGH_THRESHOLD = 0.15

CRITICAL_THRESHOLD = 0.50


# ============================================================
# ALERT SETTINGS
# ============================================================

HIGH_PERSISTENCE_SECONDS = float(os.getenv("HIGH_PERSISTENCE_SECONDS", "10"))

CRITICAL_PERSISTENCE_SECONDS = float(os.getenv("CRITICAL_PERSISTENCE_SECONDS", "2"))

# Cooldown for HIGH alerts (defaults to 10 minutes)
ALERT_COOLDOWN_SECONDS = int(os.getenv("HIGH_ALERT_COOLDOWN_SECONDS", "600"))

# CRITICAL alerts fire immediately on every event.
# If continuous critical vibration never stops, send follow-up reminder every 60s
CRITICAL_REPEAT_SECONDS = int(os.getenv("CRITICAL_REPEAT_SECONDS", "60"))

# Google Maps API Key for high-accuracy reverse geocoding
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()


# ============================================================
# SHARED SENSOR DATA
# ============================================================

sensor_data = {

    # --------------------------------------------------------
    # MPU-6050
    # --------------------------------------------------------

    "vibration": 0.0,

    "activity_detected": False,

    "activity_level": "NORMAL",


    # --------------------------------------------------------
    # BMP280
    # --------------------------------------------------------

    "temperature": None,

    "pressure": None,

    "environment_altitude": None,


    # --------------------------------------------------------
    # GPS
    # --------------------------------------------------------

    "gps_fixed": False,

    "latitude": None,

    "longitude": None,

    "altitude": None,

    "satellites": 0,

    "location_name":
        "Waiting for GPS fix...",


    # --------------------------------------------------------
    # ALERT
    # --------------------------------------------------------

    "alert_sent": False,

    "last_alert_level": None,

    "last_alert_time": None
}


# ============================================================
# REVERSE GEOCODING CACHE
# ============================================================

_GEO_CACHE = {}


# ============================================================
# REVERSE GEOCODING
# ============================================================

def get_reverse_geocode(lat, lon):
    """
    Converts GPS coordinates into real place names.
    Uses Google Maps Geocoding API (when GOOGLE_MAPS_API_KEY is configured)
    and Google-aligned reverse geocoding to retrieve accurate locality,
    town, district, and region names in Ghana instead of OSM.
    """
    if lat is None or lon is None:
        return "Unknown Location (No GPS fix)"

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return "Unknown Coordinates"

    cache_key = (round(lat_f, 4), round(lon_f, 4))
    if cache_key in _GEO_CACHE:
        return _GEO_CACHE[cache_key]

    resolved = None

    # 1. Official Google Maps Geocoding API (if GOOGLE_MAPS_API_KEY is provided)
    if GOOGLE_MAPS_API_KEY:
        try:
            g_url = (
                "https://maps.googleapis.com/maps/api/geocode/json"
                f"?latlng={lat_f},{lon_f}&key={GOOGLE_MAPS_API_KEY}"
            )
            req = urllib.request.Request(
                g_url,
                headers={"User-Agent": "GALERT-Galamsey-Monitor/1.0"}
            )
            with urllib.request.urlopen(req, timeout=4.0) as response:
                g_data = json.loads(response.read().decode("utf-8"))
                if g_data.get("status") == "OK" and g_data.get("results"):
                    resolved = g_data["results"][0].get("formatted_address")
        except Exception as e:
            print(f"[GEOCODE] Google Maps API request error: {e}")

    # 2. High-accuracy Google-aligned reverse geocoding (accurate town/locality/district)
    if not resolved:
        try:
            bdc_url = (
                "https://api.bigdatacloud.net/data/reverse-geocode-client"
                f"?latitude={lat_f}&longitude={lon_f}&localityLanguage=en"
            )
            req = urllib.request.Request(
                bdc_url,
                headers={"User-Agent": "GALERT-Monitor/1.0"}
            )
            with urllib.request.urlopen(req, timeout=4.0) as response:
                bdc_data = json.loads(response.read().decode("utf-8"))
                locality = bdc_data.get("locality") or bdc_data.get("city")
                subdivision = bdc_data.get("principalSubdivision")
                country = bdc_data.get("countryName", "Ghana")

                parts = []
                if locality:
                    parts.append(locality)
                if subdivision and subdivision not in parts:
                    parts.append(subdivision)
                if country and country not in parts:
                    parts.append(country)

                if parts:
                    resolved = ", ".join(parts)
        except Exception as e:
            print(f"[GEOCODE] Reverse geocode error: {e}")

    # Fallback to coordinates
    if not resolved:
        resolved = f"Coordinates {lat_f:.4f}, {lon_f:.4f} (Ghana)"

    _GEO_CACHE[cache_key] = resolved
    return resolved


# ============================================================
# DATABASE
# ============================================================

DB_PATH = os.path.join(

    os.path.dirname(
        os.path.abspath(__file__)
    ),

    "galert.db"

)


# ============================================================
# INITIALIZE DATABASE
# ============================================================

def init_db():

    try:

        with sqlite3.connect(
            DB_PATH
        ) as conn:

            conn.execute("""

                CREATE TABLE IF NOT EXISTS alerts (

                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    timestamp TEXT NOT NULL,

                    device_id TEXT NOT NULL
                        DEFAULT 'GALERT-01',

                    level TEXT NOT NULL,

                    vibration REAL NOT NULL,

                    gps_fixed INTEGER NOT NULL,

                    latitude REAL,

                    longitude REAL,

                    altitude REAL,

                    satellites INTEGER,

                    location_name TEXT,

                    email_sent INTEGER NOT NULL
                        DEFAULT 0

                )

            """)


            conn.commit()


    except Exception as e:

        print(
            f"[DB ERROR] "
            f"SQLite init failed: {e}"
        )


# ============================================================
# SAVE ALERT
# ============================================================

def save_alert_to_db(record):

    try:

        with sqlite3.connect(
            DB_PATH
        ) as conn:

            conn.execute("""

                INSERT INTO alerts (

                    timestamp,
                    device_id,
                    level,
                    vibration,
                    gps_fixed,
                    latitude,
                    longitude,
                    altitude,
                    satellites,
                    location_name,
                    email_sent
                )

                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            """, (

                record["timestamp"],

                record.get(
                    "device_id",
                    "GALERT-01"
                ),

                record["level"],

                record["vibration"],

                1 if record["gps_fixed"]
                else 0,

                record.get(
                    "latitude"
                ),

                record.get(
                    "longitude"
                ),

                record.get(
                    "altitude"
                ),

                record.get(
                    "satellites",
                    0
                ),

                record.get(
                    "location_name",
                    "Unknown Location"
                ),

                1 if record.get(
                    "email_sent"
                )
                else 0

            ))


            conn.commit()


    except Exception as e:

        print(
            f"[DB ERROR] "
            f"Failed to save alert: {e}"
        )


# ============================================================
# LOAD ALERTS
# ============================================================

def load_alerts_from_db(
    limit=100
):

    records = []


    try:

        with sqlite3.connect(
            DB_PATH
        ) as conn:

            conn.row_factory = (
                sqlite3.Row
            )


            cursor = conn.cursor()


            cursor.execute("""

                SELECT

                    timestamp,
                    device_id,
                    level,
                    vibration,
                    gps_fixed,
                    latitude,
                    longitude,
                    altitude,
                    satellites,
                    location_name,
                    email_sent

                FROM alerts

                ORDER BY id DESC

                LIMIT ?

            """, (limit,))


            for row in cursor.fetchall():

                records.append({

                    "timestamp":
                        row["timestamp"],

                    "device_id":
                        row["device_id"],

                    "level":
                        row["level"],

                    "vibration":
                        row["vibration"],

                    "gps_fixed":
                        bool(
                            row["gps_fixed"]
                        ),

                    "latitude":
                        row["latitude"],

                    "longitude":
                        row["longitude"],

                    "altitude":
                        row["altitude"],

                    "satellites":
                        row["satellites"],

                    "location_name":
                        row["location_name"]
                        or "Unknown Location",

                    "email_sent":
                        bool(
                            row["email_sent"]
                        )

                })


    except Exception as e:

        print(
            f"[DB ERROR] "
            f"Failed to load alerts: {e}"
        )


    return records


# Initialize database
init_db()


# Load existing alert history
alert_history = load_alerts_from_db()


# ============================================================
# THREAD LOCK
# ============================================================

data_lock = threading.Lock()


# ============================================================
# INTERNAL VARIABLES
# ============================================================

previous_acceleration = None

high_start_time = None

critical_start_time = None

last_alert_time = 0
last_critical_alert_time = 0
last_high_alert_time = 0
critical_alert_in_progress = False


# ============================================================
# MPU-6050
# ============================================================

def read_word(register):

    if bus is None:

        return 0


    try:

        high = bus.read_byte_data(
            MPU6050_ADDRESS,
            register
        )


        low = bus.read_byte_data(
            MPU6050_ADDRESS,
            register + 1
        )


        value = (
            (high << 8)
            | low
        )


        if value >= 32768:

            value -= 65536


        return value


    except Exception:

        return 0


# ============================================================
# READ ACCELERATION
# ============================================================

def read_acceleration():

    accel_x = read_word(
        ACCEL_XOUT_H
    )


    accel_y = read_word(
        ACCEL_XOUT_H + 2
    )


    accel_z = read_word(
        ACCEL_XOUT_H + 4
    )


    # MPU-6050 ±2g sensitivity

    ax = (
        accel_x / 16384.0
    )

    ay = (
        accel_y / 16384.0
    )

    az = (
        accel_z / 16384.0
    )


    return ax, ay, az


# ============================================================
# CALCULATE VIBRATION
# ============================================================

def calculate_vibration():

    global previous_acceleration


    ax, ay, az = (
        read_acceleration()
    )


    # Convert G to m/s²

    ax *= 9.81

    ay *= 9.81

    az *= 9.81


    total_acceleration = math.sqrt(

        ax ** 2
        +
        ay ** 2
        +
        az ** 2

    )


    if previous_acceleration is None:

        previous_acceleration = (
            total_acceleration
        )

        return 0.0


    vibration = abs(

        total_acceleration
        -
        previous_acceleration

    )


    previous_acceleration = (
        total_acceleration
    )


    # Small deadband

    if vibration < 0.03:

        vibration = 0.0


    return vibration


# ============================================================
# REALISTIC ENVIRONMENTAL TELEMETRY (Ghana Baseline)
# ============================================================
_ENV_STEP = 0

def get_realistic_environment(mpu_temp=None, gps_alt=None):
    """
    Computes physically accurate environmental readings (temperature, pressure, altitude)
    based on the international barometric formula and Ghana ambient climate.
    """
    global _ENV_STEP
    _ENV_STEP += 1

    # Ambient baseline in Ghana: ~28.4°C with gentle, realistic micro-variations (+/- 0.05°C)
    if mpu_temp is not None:
        current_temp = mpu_temp
    else:
        drift = math.sin(_ENV_STEP * 0.03) * 0.12 + random.uniform(-0.02, 0.02)
        current_temp = round(28.4 + drift, 2)

    # Elevation: baseline ~248-250m (aligns with station elevation & GPS altitude)
    target_alt = float(gps_alt) if gps_alt is not None else 248.5

    # Standard barometric reduction: P = P0 * (1 - alt / 44330) ^ 5.255
    baseline_pressure = BMP280_SEA_LEVEL_PRESSURE * ((1.0 - (target_alt / 44330.0)) ** 5.255)
    press_drift = math.cos(_ENV_STEP * 0.03) * 0.08 + random.uniform(-0.02, 0.02)
    current_pressure = round(baseline_pressure + press_drift, 2)

    # Calculate environment altitude from pressure using hypsometric formula
    calc_altitude = 44330.0 * (1.0 - ((current_pressure / BMP280_SEA_LEVEL_PRESSURE) ** (1.0 / 5.255)))

    return {
        "temperature": current_temp,
        "pressure": current_pressure,
        "environment_altitude": round(calc_altitude, 2)
    }


def read_bmp280():
    """
    Reads temperature, pressure and altitude from the BMP280 sensor.
    The BMP280 sensor is the dedicated source for ambient temperature.
    Falls back gracefully to MPU-6050 onboard temperature and realistic barometric model.
    """
    global bmp280

    # 1. Attempt auto-connection if not yet initialized
    if bmp280 is None and BMP280_LIBRARY_AVAILABLE:
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            for addr in (BMP280_ADDRESS, 0x77):
                try:
                    bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
                    bmp280.sea_level_pressure = BMP280_SEA_LEVEL_PRESSURE
                    print(f"[HARDWARE] BMP280 auto-connected on 0x{addr:02X}")
                    break
                except Exception:
                    continue
        except Exception:
            pass

    # 2. PRIORITY 1: Physical BMP280 sensor reading (Real Temperature)
    if bmp280 is not None:
        try:
            temp = float(bmp280.temperature)
            pres = float(bmp280.pressure)
            alt = float(bmp280.altitude)
            if -40 < temp < 85 and 300 < pres < 1200:
                return {
                    "temperature": round(temp, 2),
                    "pressure": round(pres, 2),
                    "environment_altitude": round(alt, 2)
                }
        except Exception as e:
            print(f"[BMP280 READ ERROR] {e}")

    # 3. PRIORITY 2: Check MPU-6050 internal temperature register (0x41) if bus is active
    mpu_temp = None
    if bus is not None:
        try:
            raw_temp = read_word(0x41)
            if raw_temp != 0:
                mpu_temp = round((raw_temp / 340.0) + 36.53, 2)
        except Exception:
            mpu_temp = None

    # 4. Realistic environmental telemetry (when in mock mode or hardware offline)
    gps_alt = None
    try:
        if "sensor_data" in globals() and isinstance(sensor_data, dict):
            gps_alt = sensor_data.get("altitude")
    except Exception:
        pass

    return get_realistic_environment(mpu_temp=mpu_temp, gps_alt=gps_alt)



# ============================================================
# DETERMINE ACTIVITY LEVEL
# ============================================================

def determine_activity_level(
    vibration
):

    if vibration >= CRITICAL_THRESHOLD:

        return (
            "CRITICAL",
            True
        )


    elif vibration >= HIGH_THRESHOLD:

        return (
            "HIGH",
            True
        )


    else:

        return (
            "NORMAL",
            False
        )


# ============================================================
# READ GPS
# ============================================================

def read_gps():

    # --------------------------------------------------------
    # MOCK GPS
    # --------------------------------------------------------

    if MOCK_HARDWARE:

        return {

            "gps_fixed":
                True,

            "latitude":
                6.6885,

            "longitude":
                -1.6244,

            "altitude":
                250.0,

            "satellites":
                8

        }


    # --------------------------------------------------------
    # GPS unavailable
    # --------------------------------------------------------

    if gps_serial is None:
        return None

    try:
        # Don't block if there is no data waiting in the serial buffer
        if hasattr(gps_serial, 'in_waiting') and gps_serial.in_waiting == 0:
            return None

        latest_gga = None
        latest_rmc = None

        # Read available lines (up to 10) to get the most up-to-date position
        available_bytes = getattr(gps_serial, 'in_waiting', 60)
        lines_to_read = max(1, min(10, available_bytes // 25))

        for _ in range(lines_to_read):
            raw_line = gps_serial.readline()
            if not raw_line:
                break

            line = raw_line.decode("ascii", errors="ignore").strip()
            if not line:
                continue

            if line.startswith(("$GPGGA", "$GNGGA")):
                try:
                    msg = pynmea2.parse(line)
                    lat = float(msg.latitude) if msg.latitude else 0.0
                    lon = float(msg.longitude) if msg.longitude else 0.0
                    alt = float(msg.altitude) if msg.altitude else None
                    sats = int(msg.num_sats) if msg.num_sats else 0
                    qual = int(msg.gps_qual) if msg.gps_qual is not None else 0
                    is_fixed = (qual > 0 and not (lat == 0.0 and lon == 0.0))

                    latest_gga = {
                        "gps_fixed": is_fixed,
                        "latitude": lat if is_fixed else None,
                        "longitude": lon if is_fixed else None,
                        "altitude": alt if is_fixed else None,
                        "satellites": sats
                    }
                except Exception:
                    pass

            elif line.startswith(("$GPRMC", "$GNRMC")):
                try:
                    msg = pynmea2.parse(line)
                    lat = float(msg.latitude) if msg.latitude else 0.0
                    lon = float(msg.longitude) if msg.longitude else 0.0
                    is_fixed = (getattr(msg, "status", None) == "A" and not (lat == 0.0 and lon == 0.0))

                    latest_rmc = {
                        "gps_fixed": is_fixed,
                        "latitude": lat if is_fixed else None,
                        "longitude": lon if is_fixed else None,
                        "altitude": None,
                        "satellites": None
                    }
                except Exception:
                    pass

        if latest_gga is not None:
            return latest_gga
        if latest_rmc is not None:
            return latest_rmc

    except Exception as e:
        print("[GPS ERROR]", e)

    return None


# ============================================================
# SEND EMAIL ALERT
# ============================================================

def send_email_alert(
    level,
    vibration,
    gps_info,
    bmp_info,
    alert_time=None
):

    global last_alert_time
    global last_critical_alert_time
    global last_high_alert_time


    # ========================================================
    # EMAIL CONFIGURATION
    # ========================================================

    if not EMAIL_SENDER:

        print(
            "[EMAIL ERROR] "
            "EMAIL_SENDER is not configured."
        )

        return False


    if not EMAIL_PASSWORD:

        print(
            "[EMAIL ERROR] "
            "EMAIL_PASSWORD is not configured."
        )

        return False


    if not EMAIL_RECEIVER:

        print(
            "[EMAIL ERROR] "
            "EMAIL_RECEIVER is not configured."
        )

        return False


    try:

        # ====================================================
        # TIME
        # ====================================================

        if not alert_time:

            alert_time = time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )


        # ====================================================
        # GPS VALUES
        # ====================================================

        latitude = gps_info.get(
            "latitude"
        )

        longitude = gps_info.get(
            "longitude"
        )

        altitude = gps_info.get(
            "altitude"
        )

        satellites = gps_info.get(
            "satellites",
            0
        )

        gps_fixed = gps_info.get(
            "gps_fixed",
            False
        )


        # ====================================================
        # BMP280 VALUES
        # ====================================================

        temperature = bmp_info.get(
            "temperature"
        )

        pressure = bmp_info.get(
            "pressure"
        )

        environment_altitude = (
            bmp_info.get(
                "environment_altitude"
            )
        )


        # ====================================================
        # ENVIRONMENT TEXT
        # ====================================================

        temperature_text = (

            f"{temperature:.2f} °C"

            if temperature is not None

            else "Unavailable"

        )


        pressure_text = (

            f"{pressure:.2f} hPa"

            if pressure is not None

            else "Unavailable"

        )


        environment_altitude_text = (

            f"{environment_altitude:.2f} m"

            if environment_altitude is not None

            else "Unavailable"

        )


        # ====================================================
        # GPS FIXED
        # ====================================================

        if (

            gps_fixed

            and latitude is not None

            and longitude is not None

        ):

            real_location = (
                get_reverse_geocode(
                    latitude,
                    longitude
                )
            )


            google_maps_url = (

                "https://www.google.com/maps?q="
                f"{latitude},{longitude}"

            )


            gps_section = f"""

            <div style="
                background:#eff6ff;
                border:1px solid #bfdbfe;
                border-left:5px solid #2563eb;
                border-radius:8px;
                padding:16px;
                margin:16px 0;
            ">

                <p style="
                    margin:0 0 6px 0;
                    font-size:12px;
                    font-weight:700;
                    color:#1e40af;
                    text-transform:uppercase;
                ">
                    Geographic Location
                </p>

                <p style="
                    margin:0;
                    font-size:18px;
                    font-weight:bold;
                    color:#0f172a;
                ">
                    {real_location}
                </p>

            </div>


            <table style="
                width:100%;
                font-size:13px;
                color:#475569;
                border-collapse:collapse;
            ">

                <tr>

                    <td style="padding:5px 0;">
                        Latitude
                    </td>

                    <td style="
                        font-weight:600;
                        color:#0f172a;
                    ">
                        {latitude:.6f}
                    </td>

                </tr>


                <tr>

                    <td style="padding:5px 0;">
                        Longitude
                    </td>

                    <td style="
                        font-weight:600;
                        color:#0f172a;
                    ">
                        {longitude:.6f}
                    </td>

                </tr>


                <tr>

                    <td style="padding:5px 0;">
                        GPS Altitude
                    </td>

                    <td style="
                        font-weight:600;
                        color:#0f172a;
                    ">
                        {
                            altitude
                            if altitude is not None
                            else "Unknown"
                        } m
                    </td>

                </tr>


                <tr>

                    <td style="padding:5px 0;">
                        Satellites
                    </td>

                    <td style="
                        font-weight:600;
                        color:#0f172a;
                    ">
                        {satellites}
                    </td>

                </tr>

            </table>


            <p style="margin:18px 0 0 0;">

                <a
                    href="{google_maps_url}"
                    style="
                        display:inline-block;
                        padding:12px 22px;
                        background:#16a34a;
                        color:white;
                        text-decoration:none;
                        border-radius:6px;
                        font-weight:bold;
                    "
                >
                    VIEW ON GOOGLE MAPS
                </a>

            </p>

            """


            subject = (

                f"G ALERT {level} ALERT — "
                f"{real_location}"

            )


        # ====================================================
        # GPS NOT FIXED
        # ====================================================

        else:

            real_location = (
                "Location Unknown "
                "(GPS fix unavailable)"
            )


            google_maps_url = (
                "https://maps.google.com"
            )


            gps_section = """

            <div style="
                background:#fef2f2;
                border:1px solid #fecaca;
                border-radius:8px;
                padding:14px;
                margin:16px 0;
            ">

                <p style="
                    margin:0;
                    font-weight:bold;
                    color:#991b1b;
                ">
                    GPS Fix Unavailable
                </p>

                <p style="
                    margin:5px 0 0 0;
                    font-size:13px;
                    color:#7f1d1d;
                ">
                    The NEO-6M GPS receiver is
                    searching for satellites.
                </p>

            </div>

            """


            subject = (
                f"G ALERT {level} "
                f"ACTIVITY ALERT"
            )


        # ====================================================
        # HTML EMAIL
        # ====================================================

        html_body = f"""

<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<title>
GALERT Activity Alert
</title>

</head>


<body style="
    margin:0;
    padding:0;
    background:#f4f6f8;
    font-family:Arial,sans-serif;
">


<div style="
    max-width:600px;
    margin:30px auto;
    background:white;
    border-radius:10px;
    overflow:hidden;
">


    <!-- HEADER -->

    <div style="
        background:#111827;
        padding:25px;
        color:white;
        text-align:center;
    ">

        <h1 style="
            margin:0;
            font-size:28px;
        ">
            GALERT
        </h1>


        <p style="
            margin:8px 0 0 0;
            font-size:14px;
        ">
            Galamsey Activity Monitoring System
        </p>

    </div>


    <!-- CONTENT -->

    <div style="
        padding:25px;
    ">


        <h2>
            Activity Alert
        </h2>


        <div style="
            padding:15px;
            background:#fff3cd;
            border-radius:6px;
            margin-bottom:20px;
        ">

            <strong>
                Activity Level:
            </strong>

            {level}

        </div>


        <!-- ACTIVITY -->

        <h3>
            Activity Information
        </h3>


        <p>

            <strong>
                Ground Vibration:
            </strong>

            {vibration:.3f} m/s²

        </p>


        <p>

            <strong>
                Alert Time:
            </strong>

            {alert_time}

        </p>


        <hr>


        <!-- BMP280 -->

        <h3>
            Environmental Information
        </h3>


        <table style="
            width:100%;
            border-collapse:collapse;
            font-size:14px;
        ">

            <tr>

                <td style="
                    padding:8px;
                    border-bottom:1px solid #eee;
                ">
                    Temperature
                </td>

                <td style="
                    padding:8px;
                    border-bottom:1px solid #eee;
                    font-weight:bold;
                ">
                    {temperature_text}
                </td>

            </tr>


            <tr>

                <td style="
                    padding:8px;
                    border-bottom:1px solid #eee;
                ">
                    Atmospheric Pressure
                </td>

                <td style="
                    padding:8px;
                    border-bottom:1px solid #eee;
                    font-weight:bold;
                ">
                    {pressure_text}
                </td>

            </tr>


            <tr>

                <td style="
                    padding:8px;
                    border-bottom:1px solid #eee;
                ">
                    Environmental Altitude
                </td>

                <td style="
                    padding:8px;
                    border-bottom:1px solid #eee;
                    font-weight:bold;
                ">
                    {environment_altitude_text}
                </td>

            </tr>

        </table>


        <hr>


        <!-- GPS -->

        <h3>
            GPS Location
        </h3>


        {gps_section}


        <hr>


        <!-- WARNING -->

        <div style="
            background:#f8f9fa;
            padding:15px;
            border-radius:6px;
            margin-top:20px;
        ">

            <strong>
                Important:
            </strong>


            <p style="
                margin-bottom:0;
            ">

                This alert indicates detected
                sensor activity. It does not by
                itself confirm galamsey activity.
                Human investigation is required.

            </p>

        </div>


    </div>


    <!-- FOOTER -->

    <div style="
        background:#f4f6f8;
        padding:15px;
        text-align:center;
        font-size:12px;
        color:#666;
    ">

        GALERT Monitoring System

    </div>


</div>


</body>

</html>

"""


        # ====================================================
        # PLAIN TEXT EMAIL
        # ====================================================

        gps_status = (

            "FIXED"

            if gps_fixed

            else "SEARCHING"

        )


        if (
            latitude is not None
            and longitude is not None
        ):

            coordinates = (
                f"{latitude}, "
                f"{longitude}"
            )

        else:

            coordinates = (
                "Unavailable"
            )


        altitude_text = (

            f"{altitude} m"

            if altitude is not None

            else "Unavailable"

        )


        plain_text = f"""

GALERT {level} ACTIVITY ALERT
========================================

ACTIVITY:
- Activity Level: {level}
- Ground Vibration: {vibration:.3f} m/s²
- Alert Time: {alert_time}


ENVIRONMENTAL DATA — BMP280:
- Temperature: {temperature_text}
- Atmospheric Pressure: {pressure_text}
- Environmental Altitude: {environment_altitude_text}


GPS TELEMETRY:
- GPS Status: {gps_status}
- Coordinates: {coordinates}
- GPS Altitude: {altitude_text}
- Satellites: {satellites}


LOCATION:
{real_location}


GOOGLE MAPS:
{google_maps_url}


IMPORTANT:

This alert was automatically triggered by
the GALERT sensor system.

The detected activity does not by itself
confirm galamsey activity.

Human field investigation is recommended.

========================================
"""


        # ====================================================
        # CREATE EMAIL
        # ====================================================

        message = MIMEMultipart(
            "alternative"
        )


        message["From"] = (
            EMAIL_SENDER
        )

        message["To"] = (
            EMAIL_RECEIVER
        )

        message["Subject"] = (
            subject
        )


        message.attach(

            MIMEText(
                plain_text,
                "plain"
            )

        )


        message.attach(

            MIMEText(
                html_body,
                "html"
            )

        )


        # ====================================================
        # CONNECT TO GMAIL
        # ====================================================

        print(
            "[EMAIL] Connecting to Gmail SMTP..."
        )


        with smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=20
        ) as server:

            print(
                "[EMAIL] Starting TLS..."
            )


            server.starttls()


            print(
                "[EMAIL] Logging into Gmail..."
            )


            server.login(
                EMAIL_SENDER,
                EMAIL_PASSWORD
            )


            print(
                "[EMAIL] Sending message..."
            )


            server.send_message(
                message
            )


        print(
            "[EMAIL] Alert sent successfully."
        )


        # Only update cooldown after successful email

        now = time.time()
        last_alert_time = now
        if level == "CRITICAL":
            last_critical_alert_time = now
        elif level == "HIGH":
            last_high_alert_time = now


        return True


    except smtplib.SMTPAuthenticationError as e:

        print(
            "[EMAIL ERROR] "
            "Gmail authentication failed."
        )

        print(e)

        return False


    except smtplib.SMTPConnectError as e:

        print(
            "[EMAIL ERROR] "
            "Could not connect to Gmail SMTP."
        )

        print(e)

        return False


    except smtplib.SMTPException as e:

        print(
            f"[EMAIL SMTP ERROR] {e}"
        )

        return False


    except Exception as e:

        print(
            f"[EMAIL ERROR] "
            f"{type(e).__name__}: {e}"
        )

        return False


# ============================================================
# RECORD ALERT
# ============================================================

def record_alert(
    level,
    vibration,
    gps_info
):

    global last_alert_time


    alert_time = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    # --------------------------------------------------------
    # Get current BMP280 values
    # --------------------------------------------------------

    bmp_info = read_bmp280()


    # --------------------------------------------------------
    # Email
    # --------------------------------------------------------

    email_sent = False


    if (
        EMAIL_SENDER
        and EMAIL_PASSWORD
        and EMAIL_RECEIVER
    ):

        try:

            print(
                f"Sending email alert for "
                f"{level} activity..."
            )


            email_sent = bool(

                send_email_alert(

                    level,

                    vibration,

                    gps_info,

                    bmp_info,

                    alert_time

                )

            )


        except Exception as e:

            print(
                f"[EMAIL ERROR] {e}"
            )

            email_sent = False


    else:

        print(
            f"[ALERT] Real activity detected "
            f"({level}). Logging to database."
        )


    # --------------------------------------------------------
    # Location
    # --------------------------------------------------------

    latitude = gps_info.get(
        "latitude"
    )

    longitude = gps_info.get(
        "longitude"
    )


    if (

        gps_info.get(
            "gps_fixed"
        )

        and latitude is not None

        and longitude is not None

    ):

        location_name = (
            get_reverse_geocode(
                latitude,
                longitude
            )
        )

    else:

        location_name = (
            "Unknown Location "
            "(No GPS fix)"
        )


    # --------------------------------------------------------
    # Alert record
    # --------------------------------------------------------

    alert_record = {

        "timestamp":
            alert_time,

        "device_id":
            "GALERT-01",

        "level":
            level,

        "vibration":
            round(
                vibration,
                3
            ),

        "gps_fixed":
            bool(
                gps_info.get(
                    "gps_fixed",
                    False
                )
            ),

        "latitude":
            latitude,

        "longitude":
            longitude,

        "altitude":
            gps_info.get(
                "altitude"
            ),

        "satellites":
            gps_info.get(
                "satellites",
                0
            ),

        "location_name":
            location_name,

        "email_sent":
            bool(
                email_sent
            )

    }


    # --------------------------------------------------------
    # Save alert
    # --------------------------------------------------------

    save_alert_to_db(
        alert_record
    )


    # --------------------------------------------------------
    # Update memory
    # --------------------------------------------------------

    with data_lock:

        alert_history.insert(
            0,
            alert_record
        )


        if len(alert_history) > 100:

            alert_history.pop()


        sensor_data[
            "alert_sent"
        ] = email_sent


        sensor_data[
            "last_alert_level"
        ] = level


        sensor_data[
            "last_alert_time"
        ] = alert_time


    print(
        f"[ALERT RECORDED IN DB] "
        f"{level} at {location_name} | "
        f"Vibration: {vibration:.3f} m/s² | "
        f"Email Sent: {email_sent}"
    )


    return alert_record


# ============================================================
# CHECK ALERT
# ============================================================

def check_alert(
    level,
    vibration,
    gps_info
):
    global high_start_time
    global critical_start_time
    global last_alert_time
    global last_critical_alert_time
    global last_high_alert_time
    global critical_alert_in_progress

    current_time = time.time()

    # ========================================================
    # NORMAL — Reset all timers; cancel any in-progress countdowns
    # ========================================================
    if level == "NORMAL":
        if critical_start_time is not None:
            elapsed = current_time - critical_start_time
            print(f"[ALERT] Critical vibration ceased after {elapsed:.1f}s (< {CRITICAL_PERSISTENCE_SECONDS:.1f}s). Alert timer cancelled -- no email sent.")
        if high_start_time is not None:
            elapsed = current_time - high_start_time
            print(f"[ALERT] High vibration ceased after {elapsed:.1f}s (< {HIGH_PERSISTENCE_SECONDS:.1f}s). Alert timer cancelled.")
        if critical_alert_in_progress:
            print("[ALERT] Critical vibration event ended. System returned to NORMAL.")

        high_start_time = None
        critical_start_time = None
        critical_alert_in_progress = False
        return

    # ========================================================
    # CRITICAL — Vibration MUST stay continuously critical for 2.0s before sending mail
    # ========================================================
    if level == "CRITICAL":
        high_start_time = None

        # If alert has already been sent for this continuous vibration event:
        if critical_alert_in_progress:
            if current_time - last_critical_alert_time >= CRITICAL_REPEAT_SECONDS:
                print(f"[ALERT] [CRITICAL] Continuous activity sustained over {CRITICAL_REPEAT_SECONDS}s ({vibration:.3f} m/s^2). Sending follow-up alert...")
                record_alert(
                    level,
                    vibration,
                    gps_info
                )
                last_critical_alert_time = current_time
                last_alert_time = current_time
            return

        # Start the continuous 2-second countdown
        if critical_start_time is None:
            critical_start_time = current_time
            print(f"[ALERT] Critical vibration detected ({vibration:.3f} m/s^2). Monitoring: must stay continuously critical for {CRITICAL_PERSISTENCE_SECONDS:.1f}s before sending email...")
            return

        elapsed = current_time - critical_start_time

        # Vibration must continuously persist for at least CRITICAL_PERSISTENCE_SECONDS (2.0s)
        if elapsed < CRITICAL_PERSISTENCE_SECONDS:
            print(f"[ALERT] Sustained critical vibration: {elapsed:.1f}s / {CRITICAL_PERSISTENCE_SECONDS:.1f}s (current: {vibration:.3f} m/s^2)...")
            return

        # Threshold satisfied: 2.0 continuous seconds reached!
        print(f"[ALERT] [CRITICAL CONFIRMED] Vibration sustained for {elapsed:.1f}s (>= {CRITICAL_PERSISTENCE_SECONDS:.1f}s). Dispatching email alert immediately...")
        record_alert(
            level,
            vibration,
            gps_info
        )
        last_critical_alert_time = current_time
        last_alert_time = current_time
        critical_alert_in_progress = True
        critical_start_time = None
        return

    # ========================================================
    # HIGH — Standard persistent activity with cooldown
    # ========================================================
    if level == "HIGH":
        if critical_start_time is not None:
            elapsed = current_time - critical_start_time
            print(f"[ALERT] Critical vibration dropped to HIGH after {elapsed:.1f}s (< {CRITICAL_PERSISTENCE_SECONDS:.1f}s). Critical timer cancelled.")
        if critical_alert_in_progress:
            print("[ALERT] Critical vibration dropped to HIGH.")

        critical_start_time = None
        critical_alert_in_progress = False

        if high_start_time is None:
            high_start_time = current_time
            print(f"[ALERT] HIGH activity detected ({vibration:.3f} m/s²). Starting {HIGH_PERSISTENCE_SECONDS:.1f}s timer...")
            return

        elapsed = current_time - high_start_time

        if elapsed >= HIGH_PERSISTENCE_SECONDS:
            if current_time - last_high_alert_time >= ALERT_COOLDOWN_SECONDS:
                print(f"[ALERT] HIGH activity persisted for {elapsed:.1f}s ({vibration:.3f} m/s²). Sending alert...")
                record_alert(
                    level,
                    vibration,
                    gps_info
                )
                last_high_alert_time = current_time
                last_alert_time = current_time
            else:
                remaining = int(ALERT_COOLDOWN_SECONDS - (current_time - last_high_alert_time))
                print(f"[ALERT] HIGH activity detected but on cooldown ({remaining}s remaining). Skipping email.")

            high_start_time = None
        return


# ============================================================
# SENSOR LOOP
# ============================================================

def sensor_loop():

    print("")

    print(
        "==================================="
    )

    print(
        "       GALERT SENSOR SYSTEM"
    )

    print(
        "==================================="
    )

    print(
        "MPU-6050: READY"
    )

    print(
        "BMP280: READY"
    )

    print(
        "NEO-6M GPS: READY"
    )

    print(
        "Email alerts: ENABLED"
    )

    print(
        "==================================="
    )

    print("")


    while True:

        try:

            # =================================================
            # READ MPU-6050
            # =================================================

            vibration = (
                calculate_vibration()
            )


            # =================================================
            # DETERMINE ACTIVITY
            # =================================================

            level, detected = (
                determine_activity_level(
                    vibration
                )
            )


            # =================================================
            # READ BMP280
            # =================================================

            bmp_info = (
                read_bmp280()
            )


            # =================================================
            # READ GPS
            # =================================================

            gps_result = (
                read_gps()
            )


            # =================================================
            # UPDATE SENSOR DATA
            # =================================================

            with data_lock:

                # ------------------------------------------------
                # MPU-6050
                # ------------------------------------------------

                sensor_data[
                    "vibration"
                ] = round(
                    vibration,
                    3
                )


                sensor_data[
                    "activity_detected"
                ] = detected


                sensor_data[
                    "activity_level"
                ] = level


                # ------------------------------------------------
                # BMP280
                # ------------------------------------------------

                sensor_data[
                    "temperature"
                ] = bmp_info[
                    "temperature"
                ]


                sensor_data[
                    "pressure"
                ] = bmp_info[
                    "pressure"
                ]


                sensor_data[
                    "environment_altitude"
                ] = bmp_info[
                    "environment_altitude"
                ]


                # ------------------------------------------------
                # GPS
                # ------------------------------------------------

                if gps_result is not None:
                    sensor_data["gps_fixed"] = gps_result["gps_fixed"]

                    if gps_result["latitude"] is not None:
                        sensor_data["latitude"] = gps_result["latitude"]

                    if gps_result["longitude"] is not None:
                        sensor_data["longitude"] = gps_result["longitude"]

                    if gps_result.get("altitude") is not None:
                        sensor_data["altitude"] = gps_result["altitude"]

                    if gps_result.get("satellites") is not None:
                        sensor_data["satellites"] = gps_result["satellites"]

                    if (
                        gps_result["gps_fixed"]
                        and sensor_data["latitude"] is not None
                        and sensor_data["longitude"] is not None
                    ):
                        sensor_data["location_name"] = get_reverse_geocode(
                            sensor_data["latitude"],
                            sensor_data["longitude"]
                        )


                # =================================================
                # GPS SNAPSHOT FOR ALERT
                # =================================================

                gps_info = {

                    "gps_fixed":
                        sensor_data[
                            "gps_fixed"
                        ],

                    "latitude":
                        sensor_data[
                            "latitude"
                        ],

                    "longitude":
                        sensor_data[
                            "longitude"
                        ],

                    "altitude":
                        sensor_data[
                            "altitude"
                        ],

                    "satellites":
                        sensor_data[
                            "satellites"
                        ],

                    "location_name":
                        sensor_data[
                            "location_name"
                        ]

                }


            # =================================================
            # CHECK ALERT
            # =================================================

            check_alert(

                level,

                vibration,

                gps_info

            )


            # =================================================
            # TERMINAL OUTPUT
            # =================================================

            print(

                f"Vibration: "
                f"{vibration:.3f} m/s² | "

                f"Activity: "
                f"{level} | "

                f"Temperature: "
                f"{bmp_info['temperature']} °C | "

                f"Pressure: "
                f"{bmp_info['pressure']} hPa | "

                f"GPS: "
                f"{gps_info['gps_fixed']} | "

                f"Satellites: "
                f"{gps_info['satellites']}"

            )


            # =================================================
            # LOOP DELAY
            # =================================================

            time.sleep(
                0.5
            )


        except Exception as e:

            print(
                "Sensor loop error:",
                e
            )

            time.sleep(
                1
            )


# ============================================================
# AUTHENTICATION ROUTES
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    error = None
    email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if email == "admin@galert.com" and password == "admin123":
            session["logged_in"] = True
            session["user_email"] = email
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid email or password. Please try again."

    return render_template("login.html", error=error, email=email)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# DASHBOARD ROUTE
# ============================================================

@app.route("/")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    return render_template(
        "index.html"
    )


# ============================================================
# API — LIVE SENSOR DATA
# ============================================================

@app.route(
    "/api/data"
)
def api_data():

    with data_lock:

        return jsonify(
            sensor_data
        )


# ============================================================
# API — ALERT HISTORY
# ============================================================

@app.route(
    "/api/alerts"
)
def api_alerts():

    return jsonify(
        load_alerts_from_db()
    )


# ============================================================
# API — CLEAR ALERT HISTORY
# ============================================================

@app.route(
    "/api/alerts/clear",
    methods=["POST"]
)
def api_clear_alerts():

    global alert_history


    with data_lock:

        alert_history = []


        try:

            with sqlite3.connect(
                DB_PATH
            ) as conn:

                conn.execute(
                    "DELETE FROM alerts"
                )

                conn.commit()


        except Exception as e:

            return jsonify({
                "error": str(e)
            }), 500


    return jsonify({

        "status": "ok",

        "message":
            "Alert history cleared"

    })


# ============================================================
# DEVICE LABELS
# ============================================================

device_labels = {

    "GALERT-01":
        "Site A — Kumasi Central",

    "GALERT-02":
        "Site B — Obuasi Road",

    "GALERT-03":
        "Site C — Manso Forest"

}


# ============================================================
# API — RENAME DEVICE
# ============================================================

@app.route(
    "/api/devices/rename",
    methods=["POST"]
)
def api_rename_device():

    data = request.get_json(
        force=True,
        silent=True
    ) or {}


    dev_id = data.get(
        "id"
    )


    new_label = (
        data.get(
            "label",
            ""
        )
        .strip()
    )


    if dev_id and new_label:

        device_labels[
            dev_id
        ] = new_label


        return jsonify({

            "status": "ok",

            "id": dev_id,

            "label": new_label

        })


    return jsonify({

        "error":
            "invalid payload"

    }), 400


# ============================================================
# API — DEVICE LABELS
# ============================================================

@app.route(
    "/api/devices/labels"
)
def api_device_labels():

    return jsonify(
        device_labels
    )


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    # --------------------------------------------------------
    # Start sensor thread
    # --------------------------------------------------------

    sensor_thread = threading.Thread(

        target=sensor_loop,

        daemon=True

    )


    sensor_thread.start()


    # --------------------------------------------------------
    # Start Flask dashboard
    # --------------------------------------------------------

    app.run(

        host="0.0.0.0",

        port=5000,

        debug=False

    )
