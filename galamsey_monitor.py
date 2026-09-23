import serial
import pynmea2
import smbus
import time
import math


# ==========================================
# GPS SETTINGS
# ==========================================

GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600


# ==========================================
# MPU-6050 SETTINGS
# ==========================================

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


# ==========================================
# VIBRATION SETTINGS
# ==========================================

# Temporary testing threshold
VIBRATION_THRESHOLD = 2.0


# ==========================================
# READ MPU-6050
# ==========================================

def read_acceleration():

    data = bus.read_i2c_block_data(
        MPU6050_ADDRESS,
        ACCEL_XOUT_H,
        6
    )

    accel_x = (data[0] << 8) | data[1]
    accel_y = (data[2] << 8) | data[3]
    accel_z = (data[4] << 8) | data[5]

    # Convert unsigned values to signed values
    if accel_x > 32767:
        accel_x -= 65536

    if accel_y > 32767:
        accel_y -= 65536

    if accel_z > 32767:
        accel_z -= 65536

    # Convert raw values to m/s²
    ax = (accel_x / 16384.0) * 9.81
    ay = (accel_y / 16384.0) * 9.81
    az = (accel_z / 16384.0) * 9.81

    return ax, ay, az


# ==========================================
# CALCULATE VIBRATION
# ==========================================
previous_acceleration = None


def calculate_vibration():

    global previous_acceleration

    ax, ay, az = read_acceleration()

    # Convert from g to m/s²
    ax = ax * 9.81
    ay = ay * 9.81
    az = az * 9.81

    # Calculate total acceleration
    total_acceleration = math.sqrt(
        ax ** 2 +
        ay ** 2 +
        az ** 2
    )

    # First reading
    if previous_acceleration is None:

        previous_acceleration = total_acceleration

        return 0.0

    # Measure rapid change in acceleration
    vibration = abs(
        total_acceleration - previous_acceleration
    )

    previous_acceleration = total_acceleration

    return vibration


# ==========================================
# READ GPS
# ==========================================

def read_gps(gps):

    latest_location = None

    # Read GPS data for a short period
    start_time = time.time()

    while time.time() - start_time < 1:

        line = gps.readline().decode(
            "ascii",
            errors="replace"
        ).strip()

        # GPGGA contains position information
        if line.startswith("$GPGGA"):

            try:

                msg = pynmea2.parse(line)

                if msg.gps_qual != 0:

                    latest_location = {
                        "latitude": msg.latitude,
                        "longitude": msg.longitude,
                        "altitude": msg.altitude,
                        "satellites": msg.num_sats
                    }

            except pynmea2.ParseError:
                pass

    return latest_location


# ==========================================
# START GPS
# ==========================================

gps = serial.Serial(
    GPS_PORT,
    GPS_BAUD,
    timeout=1
)


# ==========================================
# PROGRAM START
# ==========================================

print()
print("==========================================")
print("       GALAMSEY ACTIVITY MONITOR")
print("==========================================")
print("MPU-6050 + NEO-6M")
print("System started successfully.")
print()
print("Monitoring vibration and GPS...")
print("Press CTRL+C to stop.")
print("==========================================")


try:

    while True:

        # ----------------------------------
        # Read vibration
        # ----------------------------------

        vibration = calculate_vibration()


        # ----------------------------------
        # Read GPS
        # ----------------------------------

        location = read_gps(gps)


        # ----------------------------------
        # Display sensor information
        # ----------------------------------

        print()
        print("------------------------------------------")

        print(
            f"Vibration: {vibration:.2f} m/s²"
        )


        # ----------------------------------
        # Determine activity
        # ----------------------------------

        if vibration >= VIBRATION_THRESHOLD:

            print("STATUS: 🚨 ACTIVITY DETECTED")

        else:

            print("STATUS: 🟢 NORMAL")


        # ----------------------------------
        # Display GPS
        # ----------------------------------

        if location:

            print()
            print("GPS STATUS: FIXED")

            print(
                f"Latitude:   {location['latitude']:.6f}"
            )

            print(
                f"Longitude:  {location['longitude']:.6f}"
            )

            print(
                f"Altitude:   {location['altitude']:.2f} m"
            )

            print(
                f"Satellites: {location['satellites']}"
            )

        else:

            print()
            print("GPS STATUS: NO FIX")


        print("------------------------------------------")

        time.sleep(1)


except KeyboardInterrupt:

    print()
    print("==========================================")
    print("Monitoring stopped.")
    print("==========================================")


finally:

    gps.close()
    bus.close()