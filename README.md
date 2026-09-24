# GALERT — Illegal Mining (Galamsey) Activity Monitor

GALERT is an IoT monitoring system designed for Raspberry Pi to detect unauthorized illegal mining (*galamsey*) activities in real-time. It monitors ground vibrations using an MPU-6050 accelerometer and tracks geographical coordinates using a NEO-6M GPS module, serving an interactive real-time web dashboard.

---

## 🏗️ Hardware Architecture & Wiring

### 1. MPU-6050 Accelerometer / Gyroscope (I2C)
| MPU-6050 Pin | Raspberry Pi Pin | Description |
|---|---|---|
| **VCC** | Pin 1 (3.3V) | Power |
| **GND** | Pin 6 (GND) | Ground |
| **SCL** | Pin 5 (GPIO 3 / SCL) | I2C Clock |
| **SDA** | Pin 3 (GPIO 2 / SDA) | I2C Data |

### 2. NEO-6M GPS Module (UART Serial)
| NEO-6M Pin | Raspberry Pi Pin | Description |
|---|---|---|
| **VCC** | Pin 2 or 4 (5V) | Power |
| **GND** | Pin 9 (GND) | Ground |
| **TX** | Pin 10 (GPIO 15 / RXD) | GPS Transmit to Pi Receive |
| **RX** | Pin 8 (GPIO 14 / TXD) | GPS Receive from Pi Transmit |

---

## 🗄️ How Alerts Are Stored

When vibration exceeds thresholds (**HIGH: ≥ 0.15 m/s² for 10s** or **CRITICAL: ≥ 0.50 m/s² for 2s**):
1. **SQLite Database (`galert.db`)**: Every real event is permanently written to the local SQLite database table `alerts` with:
   - `timestamp` (e.g. `2026-09-24 14:30:15`)
   - `device_id` (e.g. `GALERT-01`)
   - `level` (`HIGH` or `CRITICAL`)
   - `vibration` (peak acceleration in m/s²)
   - `latitude`, `longitude`, `altitude`, `satellites`, `gps_fixed`
   - `email_sent` (1 if dispatched, 0 if email was unavailable)
2. **Persistence across Reboots**: Because alerts are stored in SQLite on disk, past incident history is never lost when the Raspberry Pi restarts or powers down.
3. **Email Notification (Optional)**: If SMTP credentials are provided in `.env`, an email alert with a direct Google Maps pin is dispatched immediately. If email is not configured, the alert is still safely captured in the database and shown on the dashboard.

---

## 🚀 Raspberry Pi / Linux Deployment

### 1. Enable I2C and Serial UART
On the Raspberry Pi terminal:
```bash
sudo raspi-config
```
- Navigate to **Interface Options** -> **I2C** -> Enable (`Yes`).
- Navigate to **Interface Options** -> **Serial Port**:
  - *"Would you like a login shell over serial?"* -> Select **No**.
  - *"Would you like the serial port hardware enabled?"* -> Select **Yes**.
- Reboot if prompted:
```bash
sudo reboot
```

### 2. Clone Repository & Install Dependencies
```bash
# Clone the repository
git clone https://github.com/your-username/galert.git
cd galert

# Install system dependencies
sudo apt update
sudo apt install -y python3-pip python3-venv i2c-tools

# Verify I2C sees the MPU-6050 (should see address 0x68)
sudo i2cdetect -y 1

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install required Python packages
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables
```bash
cp .env.example .env
nano .env
```
Ensure `MOCK_HARDWARE=false` to use real sensors. Set your email credentials if you want email alerts.

### 4. Run the Dashboard
```bash
source venv/bin/activate
python3 dashboard.py
```
Open your browser and navigate to:
```
http://<your-raspberry-pi-ip>:5000
```

---

## ⚙️ Running as a Background Service (Auto-start on Boot)

To run GALERT automatically when the Raspberry Pi boots:

1. Create a systemd service file:
```bash
sudo nano /etc/systemd/system/galert.service
```

2. Paste the following configuration (replace `pi` with your username and check paths):
```ini
[Unit]
Description=GALERT Galamsey Activity Monitoring Dashboard
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/galert
ExecStart=/home/pi/galert/venv/bin/python3 dashboard.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable galert.service
sudo systemctl start galert.service

# Check status
sudo systemctl status galert.service
```

---

## 📡 API Endpoints

- `GET /api/data`: Returns live sensor telemetry (vibration, activity level, GPS status, satellites).
- `GET /api/alerts`: Returns stored alert history from SQLite.
- `POST /api/alerts/clear`: Clears past alerts from the database.
- `GET /api/devices/labels`: Returns saved custom device location names.
- `POST /api/devices/rename`: Renames the location description for a device.
