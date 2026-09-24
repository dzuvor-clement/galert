from flask import Flask, render_template, jsonify, request
import math
import time
import threading
import smtplib
import os
import random
import sqlite3
import urllib.request
import json

# ============================================================
# LINUX / HARDWARE AUTO-DETECTION
# On Linux (Raspberry Pi), real hardware is used by default (MOCK_HARDWARE=false)
# On Windows, mock sensors are used unless MOCK_HARDWARE=false is in .env
# ============================================================

IS_LINUX = os.name != "nt"
MOCK_HARDWARE = os.getenv("MOCK_HARDWARE", "false" if IS_LINUX else "true").lower() in ("true", "1", "yes")

if MOCK_HARDWARE:
    # --- Fake smbus ---
    _AXIS_BASE = [0, 0, 16384]          # [X, Y, Z] in LSB (1g static gravity on Z)

    class _FakeSMBus:
        def __init__(self, bus): pass
        def write_byte_data(self, *a): pass
        def read_byte_data(self, addr, reg):
            offset = (reg - 0x3B)
            if 0 <= offset < 6:
                axis  = offset // 2
                is_hi = (offset % 2) == 0
                val   = _AXIS_BASE[axis]
                return (val >> 8) if is_hi else (val & 0xFF)
            return 0

    class smbus:
        SMBus = _FakeSMBus

    # --- Fake serial ---
    class _FakeSerial:
        def __init__(self, *a, **kw): pass
        def readline(self):
            lat  = 6.6885
            lon  = -1.6244
            alt  = 250.0
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
            chk = 0
            for ch in sentence[1:]:
                chk ^= ord(ch)
            return (sentence + f"*{chk:02X}\r\n").encode("ascii")
    class serial:
        class Serial(_FakeSerial): pass

    import pynmea2
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
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


# ============================================================
# HARDWARE CONFIGURATION & INITIALIZATION
# ============================================================

MPU6050_ADDRESS = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B

GPS_PORT = os.getenv("GPS_PORT", "/dev/serial0")
GPS_BAUDRATE = int(os.getenv("GPS_BAUDRATE", "9600"))

bus = None
gps_serial = None

def init_hardware():
    global bus, gps_serial
    if MOCK_HARDWARE:
        bus = smbus.SMBus(1)
        gps_serial = serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1)
        print("[HARDWARE] Running in MOCK mode (simulated sensors)")
        return

    # Real I2C MPU-6050
    if smbus is not None:
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

    # Real NEO-6M GPS Serial
    try:
        gps_serial = serial.Serial(GPS_PORT, GPS_BAUDRATE, timeout=1)
        print(f"[HARDWARE] GPS serial connected on {GPS_PORT} @ {GPS_BAUDRATE} baud")
    except Exception as e:
        print(f"[HARDWARE WARNING] Could not open GPS serial port {GPS_PORT}: {e}")
        gps_serial = None

init_hardware()


# ============================================================
# VIBRATION THRESHOLDS
# ============================================================

# These are currently TESTING values.
# They should be calibrated later using real field data.

HIGH_THRESHOLD = 0.15
CRITICAL_THRESHOLD = 0.50


# ============================================================
# ALERT SETTINGS
# ============================================================

HIGH_PERSISTENCE_SECONDS = 10

CRITICAL_PERSISTENCE_SECONDS = 2

# Prevent repeated emails for the same event
ALERT_COOLDOWN_SECONDS = 600


# ============================================================
# SHARED SENSOR DATA
# ============================================================

sensor_data = {
    "vibration": 0.0,
    "activity_detected": False,
    "activity_level": "NORMAL",
    "gps_fixed": False,
    "latitude": None,
    "longitude": None,
    "altitude": None,
    "satellites": 0,
    "location_name": "Waiting for GPS fix...",
    "alert_sent": False,
    "last_alert_level": None,
    "last_alert_time": None
}


# ============================================================
# REVERSE GEOCODING (Converts coordinates to real place names)
# ============================================================

_GEO_CACHE = {}

def get_reverse_geocode(lat, lon):
    """
    Converts (latitude, longitude) into a real town/city/region name.
    Uses OpenStreetMap Nominatim reverse geocoding with local memory caching.
    """
    if lat is None or lon is None:
        return "Unknown Location (No GPS fix)"

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return "Unknown Coordinates"

    # Cache key rounded to ~11 meters
    cache_key = (round(lat_f, 4), round(lon_f, 4))
    if cache_key in _GEO_CACHE:
        return _GEO_CACHE[cache_key]

    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat_f}&lon={lon_f}&format=json&zoom=16&addressdetails=1"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "GALERT-Galamsey-Monitor/1.0 (contact: info@galert.org)",
                "Accept": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            addr = data.get("address", {})
            parts = []

            road = addr.get("road")
            suburb = addr.get("suburb") or addr.get("neighbourhood") or addr.get("village")
            town = addr.get("town") or addr.get("city") or addr.get("municipality") or addr.get("county")
            state = addr.get("state")
            country = addr.get("country", "Ghana")

            if road and suburb:
                parts.append(f"{road}, {suburb}")
            elif suburb:
                parts.append(suburb)
            elif road:
                parts.append(road)

            if town and town not in parts:
                parts.append(town)
            if state and state not in parts:
                parts.append(state)
            if country and country not in parts:
                parts.append(country)

            resolved = ", ".join(parts) if parts else data.get("display_name", f"{lat_f:.4f}, {lon_f:.4f}")
            _GEO_CACHE[cache_key] = resolved
            return resolved
    except Exception as e:
        # Fallback if offline or timeout
        fallback = f"Coordinates {lat_f:.4f}, {lon_f:.4f} (Ghana)"
        _GEO_CACHE[cache_key] = fallback
        return fallback


# ============================================================
# ALERT HISTORY & SQLITE DATABASE PERSISTENCE
# Stores real alerts permanently in galert.db (survives reboot)
# ============================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "galert.db")

def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    device_id TEXT NOT NULL DEFAULT 'GALERT-01',
                    level TEXT NOT NULL,
                    vibration REAL NOT NULL,
                    gps_fixed INTEGER NOT NULL,
                    latitude REAL,
                    longitude REAL,
                    altitude REAL,
                    satellites INTEGER,
                    location_name TEXT,
                    email_sent INTEGER NOT NULL DEFAULT 0
                )
            """)
            try:
                conn.execute("ALTER TABLE alerts ADD COLUMN location_name TEXT")
            except Exception:
                pass
            conn.commit()
    except Exception as e:
        print(f"[DB ERROR] SQLite init failed: {e}")

def save_alert_to_db(record):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT INTO alerts (
                    timestamp, device_id, level, vibration,
                    gps_fixed, latitude, longitude, altitude,
                    satellites, location_name, email_sent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record["timestamp"],
                record.get("device_id", "GALERT-01"),
                record["level"],
                record["vibration"],
                1 if record["gps_fixed"] else 0,
                record.get("latitude"),
                record.get("longitude"),
                record.get("altitude"),
                record.get("satellites", 0),
                record.get("location_name", "Unknown Location"),
                1 if record.get("email_sent") else 0
            ))
            conn.commit()
    except Exception as e:
        print(f"[DB ERROR] Failed to save alert: {e}")

def load_alerts_from_db(limit=100):
    records = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, device_id, level, vibration,
                       gps_fixed, latitude, longitude, altitude,
                       satellites, location_name, email_sent
                FROM alerts
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            for row in cursor.fetchall():
                records.append({
                    "timestamp": row["timestamp"],
                    "device_id": row["device_id"],
                    "level": row["level"],
                    "vibration": row["vibration"],
                    "gps_fixed": bool(row["gps_fixed"]),
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "altitude": row["altitude"],
                    "satellites": row["satellites"],
                    "location_name": row["location_name"] or "Unknown Location",
                    "email_sent": bool(row["email_sent"])
                })
    except Exception as e:
        print(f"[DB ERROR] Failed to load alerts: {e}")
    return records

init_db()
alert_history = load_alerts_from_db()

# Lock protects sensor_data AND alert_history
data_lock = threading.Lock()


# ============================================================
# INTERNAL VARIABLES
# ============================================================

previous_acceleration = None
high_start_time = None
critical_start_time = None
last_alert_time = 0


# ============================================================
# MPU-6050 FUNCTIONS
# ============================================================

def read_word(register):
    if bus is None:
        return 0
    try:
        high = bus.read_byte_data(MPU6050_ADDRESS, register)
        low  = bus.read_byte_data(MPU6050_ADDRESS, register + 1)
        value = (high << 8) | low
        if value >= 32768:
            value -= 65536
        return value
    except Exception:
        return 0


def read_acceleration():

    accel_x = read_word(ACCEL_XOUT_H)

    accel_y = read_word(
        ACCEL_XOUT_H + 2
    )

    accel_z = read_word(
        ACCEL_XOUT_H + 4
    )

    # MPU-6050 ±2g sensitivity
    ax = accel_x / 16384.0

    ay = accel_y / 16384.0

    az = accel_z / 16384.0

    return ax, ay, az


# ============================================================
# CALCULATE VIBRATION
# ============================================================

def calculate_vibration():

    global previous_acceleration

    ax, ay, az = read_acceleration()


    # Convert G to m/s²

    ax *= 9.81
    ay *= 9.81
    az *= 9.81


    # Calculate total acceleration

    total_acceleration = math.sqrt(

        ax ** 2
        +
        ay ** 2
        +
        az ** 2

    )


    # First reading

    if previous_acceleration is None:

        previous_acceleration = (
            total_acceleration
        )

        return 0.0


    # Calculate change

    vibration = abs(

        total_acceleration
        -
        previous_acceleration

    )


    previous_acceleration = (
        total_acceleration
    )

    # Deadband filter: at rest / no activity, vibration is strictly 0.00
    if vibration < 0.03:
        vibration = 0.0

    return vibration


# ============================================================
# DETERMINE ACTIVITY LEVEL
# ============================================================

def determine_activity_level(vibration):

    if vibration >= CRITICAL_THRESHOLD:

        return "CRITICAL", True


    elif vibration >= HIGH_THRESHOLD:

        return "HIGH", True


    else:

        return "NORMAL", False


# ============================================================
# READ GPS
# ============================================================

def read_gps():
    if gps_serial is None:
        return None

    try:

        line = gps_serial.readline().decode(
            "ascii",
            errors="ignore"
        ).strip()


        if not line:

            return None


        if line.startswith(("$GPGGA", "$GNGGA")):

            msg = pynmea2.parse(line)


            latitude = msg.latitude

            longitude = msg.longitude

            altitude = (
                float(msg.altitude)
                if msg.altitude
                else None
            )


            satellites = (
                int(msg.num_sats)
                if msg.num_sats
                else 0
            )


            gps_fixed = (
                msg.gps_qual is not None
                and int(msg.gps_qual) > 0
            )


            return {

                "gps_fixed": gps_fixed,

                "latitude": latitude
                    if gps_fixed
                    else None,

                "longitude": longitude
                    if gps_fixed
                    else None,

                "altitude": altitude
                    if gps_fixed
                    else None,

                "satellites": satellites

            }


    except Exception as e:

        print(
            "GPS reading error:",
            e
        )


    return None


# ============================================================
# SEND EMAIL ALERT
# ============================================================

def send_email_alert(
    level,
    vibration,
    gps_info,
    alert_time=None
):

    global last_alert_time


    # --------------------------------------------------------
    # CHECK EMAIL CONFIGURATION
    # --------------------------------------------------------

    if not EMAIL_SENDER:

        print(
            "EMAIL_SENDER is not configured."
        )

        return False


    if not EMAIL_PASSWORD:

        print(
            "EMAIL_PASSWORD is not configured."
        )

        return False


    if not EMAIL_RECEIVER:

        print(
            "EMAIL_RECEIVER is not configured."
        )

        return False


    try:

        # ----------------------------------------------------
        # TIME
        # ----------------------------------------------------

        if not alert_time:
            alert_time = time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )


        # ----------------------------------------------------
        # GPS INFORMATION & REAL LOCATION REVERSE GEOCODING
        # ----------------------------------------------------

        if gps_info["gps_fixed"]:

            latitude = gps_info["latitude"]
            longitude = gps_info["longitude"]
            altitude = gps_info["altitude"]
            satellites = gps_info["satellites"]

            # Reverse geocode GPS coordinates to real place name
            real_location = get_reverse_geocode(latitude, longitude)

            # Google Maps link
            google_maps_url = (
                f"https://www.google.com/maps?q={latitude},{longitude}"
            )

            gps_section = f"""
                <div style="background:#eff6ff;border:1px solid #bfdbfe;border-left:5px solid #2563eb;border-radius:8px;padding:16px;margin:16px 0;">
                    <p style="margin:0 0 6px 0;font-size:12px;font-weight:700;color:#1e40af;text-transform:uppercase;letter-spacing:0.5px">
                        📍 Real Geographic Location
                    </p>
                    <p style="margin:0;font-size:18px;font-weight:bold;color:#0f172a;line-height:1.4">
                        {real_location}
                    </p>
                </div>

                <table style="width:100%;font-size:13px;color:#475569;margin-bottom:16px;border-collapse:collapse">
                    <tr><td style="padding:4px 0;color:#64748b">Coordinates</td><td style="font-weight:600;color:#0f172a">{latitude:.5f}° N, {abs(longitude):.5f}° W</td></tr>
                    <tr><td style="padding:4px 0;color:#64748b">Altitude</td><td style="font-weight:600;color:#0f172a">{altitude} m</td></tr>
                    <tr><td style="padding:4px 0;color:#64748b">Satellites Connected</td><td style="font-weight:600;color:#0f172a">{satellites} satellites</td></tr>
                </table>

                <p style="margin:16px 0 0 0">
                    <a
                        href="{google_maps_url}"
                        style="
                            display:inline-block;
                            padding:12px 22px;
                            background-color:#16a34a;
                            color:white;
                            text-decoration:none;
                            border-radius:6px;
                            font-weight:bold;
                            font-size:14px;
                        "
                    >
                        📍 VIEW ON GOOGLE MAPS
                    </a>
                </p>
            """

            subject = f"🚨 GALERT {level} ALERT — {real_location}"

        else:

            real_location = "Location Unknown (Searching for GPS satellites)"
            google_maps_url = "https://maps.google.com"

            gps_section = """
                <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:14px;margin:16px 0;">
                    <p style="margin:0;font-weight:bold;color:#991b1b">⚠️ GPS Fix Unavailable</p>
                    <p style="margin:4px 0 0 0;font-size:13px;color:#7f1d1d">The NEO-6M GPS receiver is searching for satellites.</p>
                </div>
            """

            subject = f"🚨 GALERT {level} ACTIVITY ALERT"


        # ----------------------------------------------------
        # HTML EMAIL
        # ----------------------------------------------------

        html_body = f"""

<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<title>
GALERT Activity Alert
</title>

</head>


<body

style="
    margin:0;
    padding:0;
    background-color:#f4f6f8;
    font-family:Arial, sans-serif;
"
>


<div

style="
    max-width:600px;
    margin:30px auto;
    background:white;
    border-radius:10px;
    overflow:hidden;
    box-shadow:0 2px 8px rgba(0,0,0,0.1);
"
>


    <!-- HEADER -->

    <div

    style="
        background:#111827;
        padding:25px;
        color:white;
        text-align:center;
    "
    >

        <h1

        style="
            margin:0;
            font-size:28px;
        "
        >

            GALERT

        </h1>


        <p

        style="
            margin:8px 0 0 0;
            font-size:14px;
        "
        >

            Galamsey Activity Monitoring System

        </p>

    </div>



    <!-- ALERT -->

    <div

    style="
        padding:25px;
    "
    >


        <h2

        style="
            margin-top:0;
        "
        >

            Activity Alert

        </h2>



        <div

        style="
            padding:15px;
            background:#fff3cd;
            border-radius:6px;
            margin-bottom:20px;
        "
        >

            <strong>
                Activity Level:
            </strong>

            {level}

        </div>



        <!-- SENSOR DATA -->

        <h3>

            Sensor Information

        </h3>



        <p>

            <strong>
                Vibration:
            </strong>

            {vibration:.2f} m/s²

        </p>



        <p>

            <strong>
                Alert Time:
            </strong>

            {alert_time}

        </p>



        <hr>



        <!-- GPS -->

        <h3>

            GPS Location

        </h3>


        {gps_section}



        <hr>



        <!-- WARNING -->

        <div

        style="
            background:#f8f9fa;
            padding:15px;
            border-radius:6px;
            margin-top:20px;
        "
        >


            <strong>

                Important:

            </strong>


            <p

            style="
                margin-bottom:0;
            "
            >

                This alert indicates detected
                sensor activity. It does not by
                itself confirm galamsey activity.
                Human investigation is required.

            </p>


        </div>


    </div>



    <!-- FOOTER -->

    <div

    style="
        background:#f4f6f8;
        padding:15px;
        text-align:center;
        font-size:12px;
        color:#666;
    "
    >

        GALERT Monitoring System

    </div>


</div>


</body>

</html>

"""


        # ----------------------------------------------------
        # CREATE EMAIL
        # ----------------------------------------------------

        message = MIMEMultipart(
            "alternative"
        )


        message["From"] = EMAIL_SENDER

        message["To"] = EMAIL_RECEIVER

        message["Subject"] = subject


        # ----------------------------------------------------
        # PLAIN TEXT VERSION
        # ----------------------------------------------------

        plain_text = f"""

GALERT {level} ACTIVITY ALERT
========================================

REAL LOCATION:
📍 {real_location}

SENSOR INFORMATION:
- Activity Level: {level}
- Ground Vibration: {vibration:.2f} m/s²
- Alert Time: {alert_time}

GPS TELEMETRY:
- GPS Status: {'FIXED' if gps_info['gps_fixed'] else 'SEARCHING'}
- Coordinates: {latitude}, {longitude}
- Altitude: {altitude} m
- Satellites: {satellites}

GOOGLE MAPS:
{google_maps_url}

IMPORTANT:
This alert was automatically triggered by ground vibration sensors. Human field investigation is recommended.
========================================

"""


        message.attach(

            MIMEText(
                plain_text,
                "plain"
            )

        )


        # ----------------------------------------------------
        # HTML VERSION
        # ----------------------------------------------------

        message.attach(

            MIMEText(
                html_body,
                "html"
            )

        )


        # ----------------------------------------------------
        # CONNECT TO GMAIL
        # ----------------------------------------------------

        with smtplib.SMTP(
            "smtp.gmail.com",
            587
        ) as server:

            server.starttls()


            server.login(

                EMAIL_SENDER,

                EMAIL_PASSWORD

            )


            server.send_message(
                message
            )


        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        print("")

        print(
            "==================================="
        )

        print(
            "       EMAIL ALERT SENT"
        )

        print(
            "==================================="
        )

        print(
            f"Level: {level}"
        )

        print(
            f"Receiver: {EMAIL_RECEIVER}"
        )

        print(
            "Google Maps location included"
        )

        print(
            "==================================="
        )

        print("")


        return True


    except Exception as e:

        print("")

        print(
            "==================================="
        )

        print(
            "       EMAIL ALERT ERROR"
        )

        print(
            "==================================="
        )

        print(e)

        print(
            "==================================="
        )

        print("")

        return False


# ============================================================
# RECORD ALERT (PERSISTENT DB + IN-MEMORY + EMAIL DISPATCH)
# Alerts are ALWAYS saved to SQLite DB, even if email fails/not set
# ============================================================

def record_alert(level, vibration, gps_info):
    global last_alert_time
    alert_time = time.strftime("%Y-%m-%d %H:%M:%S")
    last_alert_time = time.time()

    # Attempt email dispatch if credentials configured
    email_sent = False
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER:
        try:
            print(f"Sending email alert for {level} activity...")
            email_sent = bool(send_email_alert(level, vibration, gps_info, alert_time))
        except Exception as e:
            print(f"[EMAIL ERROR] {e}")
            email_sent = False
    else:
        print(f"[ALERT] Real activity detected ({level}). Logging to database.")

    # Resolve real geographic location name
    lat = gps_info.get("latitude")
    lon = gps_info.get("longitude")
    if gps_info.get("gps_fixed") and lat is not None and lon is not None:
        location_name = get_reverse_geocode(lat, lon)
    else:
        location_name = "Unknown Location (No GPS fix)"

    alert_record = {
        "timestamp": alert_time,
        "device_id": "GALERT-01",
        "level": level,
        "vibration": round(vibration, 3),
        "gps_fixed": bool(gps_info.get("gps_fixed", False)),
        "latitude": lat,
        "longitude": lon,
        "altitude": gps_info.get("altitude"),
        "satellites": gps_info.get("satellites", 0),
        "location_name": location_name,
        "email_sent": bool(email_sent)
    }

    # 1. Save to SQLite database (persists permanently on Linux)
    save_alert_to_db(alert_record)

    # 2. Update live in-memory registry
    with data_lock:
        alert_history.insert(0, alert_record)
        if len(alert_history) > 100:
            alert_history.pop()

        sensor_data["alert_sent"] = True
        sensor_data["last_alert_level"] = level
        sensor_data["last_alert_time"] = alert_time
        sensor_data["location_name"] = location_name

    print(f"[ALERT RECORDED IN DB] {level} at {location_name} | Vibration: {vibration:.3f} m/s^2 | Email Sent: {email_sent}\n")
    return alert_record


# ============================================================
# CHECK WHETHER ALERT SHOULD BE SENT
# ============================================================

def check_alert(
    level,
    vibration,
    gps_info
):

    global high_start_time
    global critical_start_time
    global last_alert_time

    current_time = time.time()

    # ========================================================
    # NORMAL
    # ========================================================

    if level == "NORMAL":
        high_start_time = None
        critical_start_time = None
        return

    # ========================================================
    # CRITICAL
    # ========================================================

    if level == "CRITICAL":
        high_start_time = None

        if critical_start_time is None:
            critical_start_time = current_time
            print("CRITICAL activity detected. Starting 2-second timer...")

        elapsed = current_time - critical_start_time

        if elapsed >= CRITICAL_PERSISTENCE_SECONDS:
            if current_time - last_alert_time >= ALERT_COOLDOWN_SECONDS:
                print("CRITICAL activity persisted.")
                record_alert(level, vibration, gps_info)
            critical_start_time = None
        return

    # ========================================================
    # HIGH
    # ========================================================

    if level == "HIGH":
        critical_start_time = None

        if high_start_time is None:
            high_start_time = current_time
            print("HIGH activity detected. Starting 10-second timer...")

        elapsed = current_time - high_start_time

        if elapsed >= HIGH_PERSISTENCE_SECONDS:
            if current_time - last_alert_time >= ALERT_COOLDOWN_SECONDS:
                print("HIGH activity persisted.")
                record_alert(level, vibration, gps_info)
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
        "     GALERT SENSOR SYSTEM"
    )

    print(
        "==================================="
    )

    print(
        "MPU-6050: READY"
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

            # ------------------------------------------------
            # READ MPU-6050
            # ------------------------------------------------

            vibration = (
                calculate_vibration()
            )


            # ------------------------------------------------
            # DETERMINE ACTIVITY
            # ------------------------------------------------

            level, detected = (
                determine_activity_level(
                    vibration
                )
            )


            # ------------------------------------------------
            # READ GPS
            # ------------------------------------------------

            gps_result = read_gps()


            # ------------------------------------------------
            # UPDATE GPS DATA
            # ------------------------------------------------

            with data_lock:

                sensor_data[
                    "vibration"
                ] = vibration


                sensor_data[
                    "activity_detected"
                ] = detected


                sensor_data[
                    "activity_level"
                ] = level


                if gps_result is not None:

                    sensor_data[
                        "gps_fixed"
                    ] = gps_result[
                        "gps_fixed"
                    ]


                    sensor_data[
                        "latitude"
                    ] = gps_result[
                        "latitude"
                    ]


                    sensor_data[
                        "longitude"
                    ] = gps_result[
                        "longitude"
                    ]


                    sensor_data[
                        "altitude"
                    ] = gps_result[
                        "altitude"
                    ]


                    sensor_data[
                        "satellites"
                    ] = gps_result[
                        "satellites"
                    ]


                    if gps_result["gps_fixed"] and gps_result["latitude"] is not None and gps_result["longitude"] is not None:
                        sensor_data[
                            "location_name"
                        ] = get_reverse_geocode(
                            gps_result["latitude"],
                            gps_result["longitude"]
                        )


                # Create GPS snapshot

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
                        sensor_data.get(
                            "location_name",
                            "Unknown Location"
                        )

                }


            # ------------------------------------------------
            # CHECK ALERT
            # ------------------------------------------------

            check_alert(

                level,

                vibration,

                gps_info

            )


            # ------------------------------------------------
            # TERMINAL OUTPUT
            # ------------------------------------------------

            print(

                f"Vibration: "
                f"{vibration:.3f} m/s² | "

                f"Activity: "
                f"{level} | "

                f"GPS: "
                f"{gps_info['gps_fixed']} | "

                f"Satellites: "
                f"{gps_info['satellites']}"

            )


            # ------------------------------------------------
            # SENSOR LOOP DELAY
            # ------------------------------------------------

            time.sleep(0.5)


        except Exception as e:

            print(
                "Sensor loop error:",
                e
            )

            time.sleep(1)


# ============================================================
# DASHBOARD ROUTE
# ============================================================

@app.route("/")
def dashboard():

    return render_template(
        "index.html"
    )


# ============================================================
# API ROUTE — live sensor data
# ============================================================

@app.route("/api/data")
def api_data():

    with data_lock:

        return jsonify(
            sensor_data
        )


# ============================================================
# API ROUTE — alert history
# ============================================================

@app.route("/api/alerts")
def api_alerts():
    return jsonify(load_alerts_from_db())


@app.route("/api/alerts/clear", methods=["POST"])
def api_clear_alerts():
    global alert_history
    with data_lock:
        alert_history = []
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM alerts")
                conn.commit()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ok", "message": "Alert history cleared"})


# ============================================================
# API ROUTE — device location renaming
# ============================================================

device_labels = {
    "GALERT-01": "Site A — Kumasi Central",
    "GALERT-02": "Site B — Obuasi Road",
    "GALERT-03": "Site C — Manso Forest",
}

@app.route("/api/devices/rename", methods=["POST"])
def api_rename_device():
    data = request.get_json(force=True, silent=True) or {}
    dev_id = data.get("id")
    new_label = data.get("label", "").strip()
    if dev_id and new_label:
        device_labels[dev_id] = new_label
        return jsonify({"status": "ok", "id": dev_id, "label": new_label})
    return jsonify({"error": "invalid payload"}), 400

@app.route("/api/devices/labels")
def api_device_labels():
    return jsonify(device_labels)


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    # Start sensor thread

    sensor_thread = threading.Thread(

        target=sensor_loop,

        daemon=True

    )


    sensor_thread.start()


    # Start Flask dashboard

    app.run(

        host="0.0.0.0",

        port=5000,

        debug=False

    )