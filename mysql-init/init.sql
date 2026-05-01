CREATE TABLE IF NOT EXISTS turbines (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    location        VARCHAR(255) NOT NULL,

    -- Value Object: Health_Status
    health_status   ENUM('Healthy', 'Degraded', 'Critical') NOT NULL DEFAULT 'Healthy',
    temperature     FLOAT,
    vibration       FLOAT,

    -- Value Object: Anomaly_Detected
    anomaly_detected    BOOLEAN DEFAULT FALSE,
    anomaly_description VARCHAR(255),

    -- Value Object: Operating_Hours
    operating_hours FLOAT DEFAULT 0,

    -- Value Object: Weather_Forecast
    wind_speed      FLOAT,
    forecast_temp   FLOAT,

    updated_at      DATETIME DEFAULT NOW() ON UPDATE NOW(),
    created_at      DATETIME DEFAULT NOW()
);

-- Testdata
INSERT INTO turbines (name, location, health_status, temperature, vibration, operating_hours, wind_speed, forecast_temp)
VALUES
    ('Turbine-DK-001', 'Esbjerg Offshore', 'Healthy',  38.2, 1.4, 4821.5, 11.2, 14.0),
    ('Turbine-DK-002', 'Horns Rev',        'Degraded', 67.5, 4.1, 9203.0,  8.7, 12.5);