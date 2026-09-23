// ==========================================
// CREATE MAP
// ==========================================

let map = L.map("map").setView(
    [5.6037, -0.1870],
    13
);


// OpenStreetMap tiles

L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
        attribution:
            "&copy; OpenStreetMap contributors"
    }
).addTo(map);


// GPS marker

let marker = null;


// ==========================================
// UPDATE DASHBOARD
// ==========================================

function updateDashboard(data) {

    // Vibration

    document.getElementById(
        "vibration"
    ).textContent =
        data.vibration.toFixed(2);


    document.getElementById(
        "vibration2"
    ).textContent =
        data.vibration.toFixed(2);


    // Activity status

    const status =
        document.getElementById(
            "activityStatus"
        );


    const message =
        document.getElementById(
            "activityMessage"
        );


    if (data.activity_detected) {

        status.textContent =
            "ACTIVITY DETECTED";

        status.style.color =
            "#dc2626";

        message.textContent =
            "Suspicious vibration activity detected";

    } else {

        status.textContent =
            "NORMAL";

        status.style.color =
            "#16a34a";

        message.textContent =
            "No suspicious activity detected";
    }


    // GPS

    document.getElementById(
        "gpsStatus"
    ).textContent =
        data.gps_fixed
            ? "FIXED"
            : "NO FIX";


    document.getElementById(
        "satellites"
    ).textContent =
        data.satellites;


    if (data.gps_fixed) {

        document.getElementById(
            "latitude"
        ).textContent =
            data.latitude.toFixed(6);


        document.getElementById(
            "longitude"
        ).textContent =
            data.longitude.toFixed(6);


        document.getElementById(
            "altitude"
        ).textContent =
            data.altitude.toFixed(2);


        // Update map

        const position = [
            data.latitude,
            data.longitude
        ];


        if (marker === null) {

            marker = L.marker(
                position
            ).addTo(map);

        } else {

            marker.setLatLng(
                position
            );
        }


        marker.bindPopup(
            "IoT Monitoring Location"
        );


        map.setView(
            position,
            16
        );
    }
}


// ==========================================
// GET DATA FROM RASPBERRY PI
// ==========================================

async function getSensorData() {

    try {

        const response =
            await fetch("/api/data");

        const data =
            await response.json();

        updateDashboard(data);

    } catch (error) {

        console.error(
            "Could not get sensor data:",
            error
        );
    }
}


// Update every 1 second

setInterval(
    getSensorData,
    1000
);


// First request

getSensorData();