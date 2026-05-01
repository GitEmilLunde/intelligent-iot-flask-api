from flask import Flask, jsonify, request
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)


def add(a, b):  # bevares til CI-test
    return a + b


def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )


# ---------- FORRETNINGSLOGIK: GRÆNSEVÆRDIER ----------
#
# Baseret på typiske SCADA-alarmgrænser for offshore vindmøller (IEC 61400):
#
#   Temperatur  (gearkasse/generator, °C):
#     Healthy   < 70
#     Degraded  70 – 90
#     Critical  > 90
#
#   Vibration   (RMS hastighed, mm/s):
#     Healthy   < 2.5
#     Degraded  2.5 – 6.0
#     Critical  > 6.0
#
#   Vindhastighed (m/s):
#     IEC cut-out = 25 m/s – over det lukker møllen ned
#     > 25  →  Degraded + anomali

_TEMP_DEGRADED  = 70.0   # °C
_TEMP_CRITICAL  = 90.0   # °C
_VIB_DEGRADED   = 2.5    # mm/s
_VIB_CRITICAL   = 6.0    # mm/s
_WIND_CUTOUT    = 25.0   # m/s


def _evaluate_health(temperature, vibration, wind_speed):
    """Beregner health_status, anomaly_detected og anomaly_description
    ud fra sensorværdier. Den alvorligste status vinder."""
    status = "Healthy"
    anomalies = []

    if temperature is not None:
        if temperature > _TEMP_CRITICAL:
            status = "Critical"
            anomalies.append(f"Kritisk temperatur {temperature}°C (grænse {_TEMP_CRITICAL}°C)")
        elif temperature > _TEMP_DEGRADED:
            if status != "Critical":
                status = "Degraded"
            anomalies.append(f"Høj temperatur {temperature}°C (grænse {_TEMP_DEGRADED}°C)")

    if vibration is not None:
        if vibration > _VIB_CRITICAL:
            status = "Critical"
            anomalies.append(f"Kritisk vibration {vibration} mm/s (grænse {_VIB_CRITICAL})")
        elif vibration > _VIB_DEGRADED:
            if status != "Critical":
                status = "Degraded"
            anomalies.append(f"Høj vibration {vibration} mm/s (grænse {_VIB_DEGRADED})")

    if wind_speed is not None and wind_speed > _WIND_CUTOUT:
        if status != "Critical":
            status = "Degraded"
        anomalies.append(f"Vindhastighed over cut-out {wind_speed} m/s (grænse {_WIND_CUTOUT})")

    return status, bool(anomalies), "; ".join(anomalies) if anomalies else None


# ---------- BASIC ROUTES ----------

@app.route("/ping", methods=["GET"])
def ping():
    return "pong from Windmill Predictive Maintenance API"


@app.route("/")
def index():
    return "Vindmølle API kører. Prøv /api/turbines"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ---------- TURBINES API ----------

@app.route("/api/turbines", methods=["GET"])
def get_turbines():
    """
    Hent alle vindmøller med samtlige value objects.
    Returnerer: id, name, location, health_status, temperature,
                vibration, anomaly_detected, anomaly_description,
                operating_hours, wind_speed, forecast_temp,
                updated_at, created_at
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM turbines")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(rows)


@app.route("/api/turbines/<int:turbine_id>", methods=["GET"])
def get_turbine(turbine_id):
    """
    Hent én vindmølle med alle value objects.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM turbines WHERE id = %s", (turbine_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return jsonify(row)
    return jsonify({"error": "Turbine not found"}), 404


@app.route("/api/turbines", methods=["POST"])
def create_turbine():
    """
    Opret ny vindmølle (entity: WindMill_Turbine).
    Påkrævet: name, location
    Valgfri:  health_status, temperature, vibration,
              anomaly_detected, anomaly_description,
              operating_hours, wind_speed, forecast_temp
    """
    data = request.get_json()
    if not data or not all(f in data for f in ["name", "location"]):
        return jsonify({"error": "Missing name or location"}), 400

    temperature   = data.get("temperature")
    vibration     = data.get("vibration")
    wind_speed    = data.get("wind_speed")
    health_status, anomaly_detected, anomaly_description = _evaluate_health(
        temperature, vibration, wind_speed
    )

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO turbines (
            name, location, health_status, temperature, vibration,
            anomaly_detected, anomaly_description,
            operating_hours, wind_speed, forecast_temp
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            data["name"],
            data["location"],
            health_status,
            temperature,
            vibration,
            anomaly_detected,
            anomaly_description,
            data.get("operating_hours", 0),
            wind_speed,
            data.get("forecast_temp")
        )
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return jsonify({"id": new_id, "name": data["name"], "location": data["location"],
                    "health_status": health_status, "anomaly_detected": anomaly_detected,
                    "anomaly_description": anomaly_description}), 201


@app.route("/api/turbines/<int:turbine_id>", methods=["PUT"])
def update_turbine(turbine_id):
    """
    Opdatér vindmølle – erstatter value objects med nye værdier (nyt snapshot).
    Alle felter er valgfrie – kun dem du sender bliver opdateret.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM turbines WHERE id = %s", (turbine_id,))
    existing = cursor.fetchone()
    if not existing:
        cursor.close()
        conn.close()
        return jsonify({"error": "Turbine not found"}), 404

    # Flet indkommende data med eksisterende værdier (partial update)
    temperature     = data.get("temperature",     existing["temperature"])
    vibration       = data.get("vibration",       existing["vibration"])
    wind_speed      = data.get("wind_speed",      existing["wind_speed"])
    operating_hours = data.get("operating_hours", existing["operating_hours"])
    forecast_temp   = data.get("forecast_temp",   existing["forecast_temp"])

    # Beregn health automatisk ud fra sensorværdier
    health_status, anomaly_detected, anomaly_description = _evaluate_health(
        temperature, vibration, wind_speed
    )

    cursor.execute(
        """
        UPDATE turbines
        SET health_status       = %s,
            temperature         = %s,
            vibration           = %s,
            anomaly_detected    = %s,
            anomaly_description = %s,
            operating_hours     = %s,
            wind_speed          = %s,
            forecast_temp       = %s
        WHERE id = %s
        """,
        (
            health_status,
            temperature,
            vibration,
            anomaly_detected,
            anomaly_description,
            operating_hours,
            wind_speed,
            forecast_temp,
            turbine_id
        )
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": f"Turbine {turbine_id} updated",
                    "health_status": health_status,
                    "anomaly_detected": anomaly_detected,
                    "anomaly_description": anomaly_description})


@app.route("/api/turbines/<int:turbine_id>", methods=["DELETE"])
def delete_turbine(turbine_id):
    """
    Slet vindmølle.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM turbines WHERE id = %s", (turbine_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "Turbine not found"}), 404

    cursor.execute("DELETE FROM turbines WHERE id = %s", (turbine_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": f"Turbine {turbine_id} deleted"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)