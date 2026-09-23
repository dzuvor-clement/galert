from mpu6050 import mpu6050
import time
import math

# MPU-6050 I2C address
MPU_ADDRESS = 0x68

# Create sensor
sensor = mpu6050(MPU_ADDRESS)

print("========================================")
print("       PHONE VIBRATION TEST")
print("========================================")
print("Place the MPU-6050 on your phone.")
print("Turn phone vibration ON.")
print("Press CTRL+C to stop.")
print("----------------------------------------")

try:
    while True:

        # Read accelerometer
        accel = sensor.get_accel_data()

        # Get X, Y and Z acceleration
        x = accel['x']
        y = accel['y']
        z = accel['z']

        # Calculate total acceleration
        total_acceleration = math.sqrt(
            x**2 + y**2 + z**2
        )

        # Remove the effect of gravity (~9.81 m/s²)
        vibration = abs(total_acceleration - 9.81)

        # Determine vibration level
        if vibration < 0.3:
            level = "NORMAL"
        elif vibration < 1.5:
            level = "VIBRATION DETECTED"
        else:
            level = "HIGH VIBRATION"

        print(
            f"X: {x:6.2f} | "
            f"Y: {y:6.2f} | "
            f"Z: {z:6.2f} | "
            f"Vibration: {vibration:6.2f} m/s² | "
            f"{level}"
        )

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nTest stopped.")