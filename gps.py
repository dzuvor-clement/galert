import serial
import pynmea2
import smbus
import time
import math


# ==============================
# GPS SETTINGS
# ==============================

GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600


# ==============================
# MPU-6050 SETTINGS
# ==============================

MPU6050_ADDRESS = 0x68

PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B

bus = smbus.SMBus(1)

# Wake up MPU-6050
bus.write_byte_data(MPU6050_ADDRESS, PWR_MGMT_1, 0)


# ==============================
# VIBRATION THRESHOLD
# ==============================

VIBRATION_THRESHOLD = 2.0


# ==============================
# FUNCTIONS
# ==============================

def read_acceleration():

    data = bus.read_i2c_block_data(
        MPU6050_ADDRESS,
        ACCEL_XOUT_H,
        6
    )

    accel_x = (data[0] << 8) | data[1]
    accel_y = (data[2] << 8) | data[3]
    accel_z = (data[4] << 8) | data[5]

    # Convert signed values
    if accel_x > 32767:
        accel_x -= 65536

    if accel_y > 32767:
        accel_y -= 65536

    if accel_z > 32767:
        accel_z -= 65536

    # Convert to m/s²
    ax = (accel_x / 16384.0) * 9.81
    ay = (accel_y / 16384.0) * 9.81
    az = (accel_z / 16384.0) * 9.81

    return ax, ay, az


def calculate_vibration():

    ax, ay, az = read_acceleration()

    total_acceleration = math.sqrt(
        ax ** 2 +
        ay ** 2 +
        az ** 2
    )

    vibration = abs(total_acceleration - 9.81)

    return vibration


def get_gps_location(gps):

    start_time = time.time()

    while time.time() - start_time < 5:

        line = gps.readline().decode(
            "ascii",
            errors="replace"
        ).strip()

        if line.startswith("$GPGGA"):

            try:

                msg = pynmea2.parse(line)

                if msg.gps_qual != 0:

                    return (
                        msg.latitude,
                        msg.longitude,
                        msg.altitude,
                        msg.num_sats
                    )

            except pynmea2.ParseError:
                pass

    return None


# ==============================
# START GPS
# ==============================

gps = serial.Serial(
    GPS_PORT,
    GPS_BAUD,
    timeout=1
)


print("========================================")
print("      VEHICLE MONITORING TEST")
print("========================================")
print("MPU-6050 + NEO-6M")
print("System started...")
print("Press CTRL+C to stop.")
print("----------------------------------------")


try:

    while True:

        vibration = calculate_vibration()

        print(
            f"Vibration: {vibration:.2f} m/s²"
        )


        # ==============================
        # VIBRATION DETECTION
        # ==============================

        if vibration > VIBRATION_THRESHOLD:

            print()
            print("🚨 VIBRATION DETECTED!")
            print("----------------------------------------")

            print("Checking GPS location...")

            location = get_gps_location(gps)

            if location:

                latitude, longitude, altitude, satellites = location

                print()
                print("GPS LOCATION")
                print("----------------------------------------")
                print(f"Latitude:   {latitude:.6f}")
                print(f"Longitude:  {longitude:.6f}")
                print(f"Altitude:   {altitude:.2f} m")
                print(f"Satellites: {satellites}")

            else:

                print("GPS location unavailable.")
                print("Waiting for satellite fix...")

            print("----------------------------------------")


        time.sleep(0.5)


except KeyboardInterrupt:

    print()
    print("System stopped.")


finally:

    gps.close()
    bus.close()