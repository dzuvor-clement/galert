import time
import board
import busio
import adafruit_bmp280


# Create I2C connection
i2c = busio.I2C(board.SCL, board.SDA)

# Create BMP280 sensor
bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(
    i2c,
    address=0x76
)

# Set sea-level pressure
bmp280.sea_level_pressure = 1013.25

print("BMP280 Sensor Test")
print("===================")

while True:
    temperature = bmp280.temperature
    pressure = bmp280.pressure
    altitude = bmp280.altitude

    print(f"Temperature : {temperature:.2f} °C")
    print(f"Pressure    : {pressure:.2f} hPa")
    print(f"Altitude    : {altitude:.2f} m")
    print("-----------------------------")

    time.sleep(2)