from flask import Flask, render_template, jsonify
import smbus
import serial
import pynmea2
import math
import time
import threading
import smtplib
import os

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


# ============================================================
# MPU-6050 CONFIGURATION
# ============================================================

MPU6050_ADDRESS = 0x68

PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B

bus = smbus.SMBus(1)

# Wake up MPU-6050
bus.write_byte_data(
    MPU6050_ADDRESS,
    PWR_MGMT_1,
    0
)


# ============================================================
# GPS CONFIGURATION
# ============================================================

GPS_PORT = "/dev/serial0"
GPS_BAUDRATE = 9600

gps_serial = serial.Serial(
    GPS_PORT,
    GPS_BAUDRATE,
    timeout=1
)


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

    "alert_sent": False,

    "last_alert_level": None,

    "last_alert_time": None
}


# Lock protects sensor_data
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

    high = bus.read_byte_data(
        MPU6050_ADDRESS,
        register
    )

    low = bus.read_byte_data(
        MPU6050_ADDRESS,
        register + 1
    )

    value = (high << 8) | low

    if value >= 32768:
        value -= 65536

    return value


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

    try:

        line = gps_serial.readline().decode(
            "ascii",
            errors="ignore"
        ).strip()


        if not line:

            return None


        if line.startswith("$GPGGA"):

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
    gps_info
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

        alert_time = time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )


        # ----------------------------------------------------
        # GPS INFORMATION
        # ----------------------------------------------------

        if gps_info["gps_fixed"]:

            latitude = gps_info["latitude"]

            longitude = gps_info["longitude"]

            altitude = gps_info["altitude"]

            satellites = gps_info["satellites"]


            # Google Maps link

            google_maps_url = (

                "https://www.google.com/maps?q="

                f"{latitude},{longitude}"

            )


            gps_section = f"""

                <p>
                    <strong>Latitude:</strong>
                    {latitude}
                </p>


                <p>
                    <strong>Longitude:</strong>
                    {longitude}
                </p>


                <p>
                    <strong>Altitude:</strong>
                    {altitude} m
                </p>


                <p>
                    <strong>Satellites:</strong>
                    {satellites}
                </p>


                <p>

                    <a
                        href="{google_maps_url}"

                        style="
                            display:inline-block;
                            padding:12px 20px;
                            background-color:#1a73e8;
                            color:white;
                            text-decoration:none;
                            border-radius:6px;
                            font-weight:bold;
                        "
                    >

                        📍 VIEW LOCATION ON GOOGLE MAPS

                    </a>

                </p>

            """


        else:

            gps_section = """

                <p>
                    GPS position unavailable.
                </p>

                <p>
                    The NEO-6M currently has no
                    satellite fix.
                </p>

            """


        # ----------------------------------------------------
        # EMAIL SUBJECT
        # ----------------------------------------------------

        subject = (

            f"GALERT {level} ACTIVITY ALERT"

        )


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

GALERT ACTIVITY ALERT

Activity Level: {level}

Vibration:
{vibration:.2f} m/s²

Time:
{alert_time}


GPS INFORMATION
---------------

GPS Fixed:
{gps_info["gps_fixed"]}

Latitude:
{gps_info["latitude"]}

Longitude:
{gps_info["longitude"]}

Altitude:
{gps_info["altitude"]}

Satellites:
{gps_info["satellites"]}


This alert indicates detected
sensor activity.

It does not by itself confirm
galamsey activity.

Human investigation is required.

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


        last_alert_time = time.time()


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

        # Reset HIGH timer

        high_start_time = None


        # Start CRITICAL timer

        if critical_start_time is None:

            critical_start_time = (
                current_time
            )

            print(
                "CRITICAL activity detected."
            )

            print(
                "Starting 2-second timer..."
            )


        elapsed = (

            current_time
            -
            critical_start_time

        )


        # Check persistence

        if elapsed >= CRITICAL_PERSISTENCE_SECONDS:

            # Check cooldown

            if (

                current_time
                -
                last_alert_time

                >= ALERT_COOLDOWN_SECONDS

            ):

                print(
                    "CRITICAL activity persisted."
                )

                print(
                    "Sending email alert..."
                )


                sent = send_email_alert(

                    level,

                    vibration,

                    gps_info

                )


                if sent:

                    with data_lock:

                        sensor_data[
                            "alert_sent"
                        ] = True

                        sensor_data[
                            "last_alert_level"
                        ] = level

                        sensor_data[
                            "last_alert_time"
                        ] = time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )


            # Prevent another immediate alert

            critical_start_time = None


        return


    # ========================================================
    # HIGH
    # ========================================================

    if level == "HIGH":

        # Reset CRITICAL timer

        critical_start_time = None


        # Start HIGH timer

        if high_start_time is None:

            high_start_time = (
                current_time
            )

            print(
                "HIGH activity detected."
            )

            print(
                "Starting 10-second timer..."
            )


        elapsed = (

            current_time
            -
            high_start_time

        )


        # Check persistence

        if elapsed >= HIGH_PERSISTENCE_SECONDS:

            # Check cooldown

            if (

                current_time
                -
                last_alert_time

                >= ALERT_COOLDOWN_SECONDS

            ):

                print(
                    "HIGH activity persisted."
                )

                print(
                    "Sending email alert..."
                )


                sent = send_email_alert(

                    level,

                    vibration,

                    gps_info

                )


                if sent:

                    with data_lock:

                        sensor_data[
                            "alert_sent"
                        ] = True

                        sensor_data[
                            "last_alert_level"
                        ] = level

                        sensor_data[
                            "last_alert_time"
                        ] = time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )


            # Reset timer

            high_start_time = None


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
                        ]

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
# API ROUTE
# ============================================================

@app.route("/api/data")
def api_data():

    with data_lock:

        return jsonify(
            sensor_data
        )


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