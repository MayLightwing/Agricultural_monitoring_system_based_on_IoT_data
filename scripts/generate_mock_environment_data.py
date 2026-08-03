from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path


OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "mock_environment_data.csv"
RECORD_COUNT = 1000
START_TIME = datetime(2026, 8, 3, 0, 0)
RANDOM_SEED = 20260803
FIELD_WIDTH_M = 120.0
FIELD_HEIGHT_M = 80.0
GRID_COLUMNS = 6
GRID_ROWS = 4
CELL_WIDTH_M = FIELD_WIDTH_M / GRID_COLUMNS
CELL_HEIGHT_M = FIELD_HEIGHT_M / GRID_ROWS
WAYPOINTS_PER_LOOP = GRID_COLUMNS * GRID_ROWS
UNCERTAINTY_CASES = {
    120: "sensor_missing_soil_moisture",
    360: "data_conflict_vision_drought_soil_normal",
    600: "low_vision_confidence",
    840: "noisy_temperature_spike",
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def simulate_image_label(
    temperature: float,
    soil_moisture: float,
    rainfall: float,
) -> tuple[str, float]:
    if soil_moisture < 22 and temperature > 29:
        return "drought", random.uniform(0.74, 0.91)

    if rainfall > 8 and soil_moisture > 50:
        return "waterlogging", random.uniform(0.70, 0.88)

    if random.random() < 0.07:
        return "pest", random.uniform(0.62, 0.84)

    if random.random() < 0.04:
        return "unknown", random.uniform(0.28, 0.48)

    return "healthy", random.uniform(0.82, 0.97)


def simulate_robot_pose(index: int) -> dict[str, str]:
    waypoint = index % WAYPOINTS_PER_LOOP
    grid_row = waypoint // GRID_COLUMNS
    row_offset = waypoint % GRID_COLUMNS
    is_forward_row = grid_row % 2 == 0
    grid_col = row_offset if is_forward_row else GRID_COLUMNS - row_offset - 1

    x = (grid_col + 0.5) * CELL_WIDTH_M + 1.5 * math.sin(index * 0.7)
    y = (grid_row + 0.5) * CELL_HEIGHT_M + 1.0 * math.cos(index * 0.5)
    x = clamp(x, 0, FIELD_WIDTH_M)
    y = clamp(y, 0, FIELD_HEIGHT_M)
    heading = 90.0 if is_forward_row else 270.0

    return {
        "robot_x_m": f"{x:.1f}",
        "robot_y_m": f"{y:.1f}",
        "robot_heading_deg": f"{heading:.0f}",
        "region_id": f"R{grid_row + 1:02d}C{grid_col + 1:02d}",
        "path_segment": f"row_{grid_row + 1}",
        "patrol_loop": str(index // WAYPOINTS_PER_LOOP + 1),
    }


def generate_rows() -> list[dict[str, str]]:
    random.seed(RANDOM_SEED)
    rows: list[dict[str, str]] = []
    soil_moisture = 38.0
    rain_event_remaining = 0

    for index in range(RECORD_COUNT):
        current_time = START_TIME + timedelta(hours=index)
        hour = current_time.hour
        day_phase = math.sin((hour - 6) / 24 * 2 * math.pi)
        seasonal_phase = math.sin(index / 24 / 14 * 2 * math.pi)

        temperature = 25 + 8 * day_phase + 2.5 * seasonal_phase + random.gauss(0, 1.2)
        temperature = clamp(temperature, 12, 42)

        humidity = 72 - 0.9 * (temperature - 22) + random.gauss(0, 5)
        humidity = clamp(humidity, 28, 98)

        if rain_event_remaining <= 0 and random.random() < 0.055:
            rain_event_remaining = random.randint(1, 5)

        if rain_event_remaining > 0:
            rainfall = random.uniform(1.2, 12.0)
            rain_event_remaining -= 1
        else:
            rainfall = 0.0

        daylight = max(0.0, math.sin((hour - 6) / 12 * math.pi))
        cloud_factor = 1 - min(rainfall / 20, 0.55)
        light = daylight * cloud_factor * random.uniform(780, 1020)
        light = clamp(light, 0, 1000)

        evaporation = max(0, temperature - 18) * 0.08 + light / 1000 * 0.45
        soil_moisture += rainfall * 0.9 - evaporation + random.gauss(0, 0.35)
        soil_moisture = clamp(soil_moisture, 8, 65)
        image_status, vision_confidence = simulate_image_label(
            temperature,
            soil_moisture,
            rainfall,
        )
        uncertainty_case = UNCERTAINTY_CASES.get(index, "normal")

        if uncertainty_case == "sensor_missing_soil_moisture":
            soil_moisture_text = ""
        elif uncertainty_case == "data_conflict_vision_drought_soil_normal":
            soil_moisture_text = "42.0"
            image_status = "drought"
            vision_confidence = 0.84
        else:
            soil_moisture_text = f"{soil_moisture:.1f}"

        if uncertainty_case == "low_vision_confidence":
            image_status = "unknown"
            vision_confidence = 0.35

        if uncertainty_case == "noisy_temperature_spike":
            temperature = 52.0

        rows.append(
            {
                "timestamp": current_time.strftime("%Y-%m-%d %H:%M"),
                "temperature": f"{temperature:.1f}",
                "humidity": f"{humidity:.1f}",
                "soil_moisture": soil_moisture_text,
                "light": f"{light:.0f}",
                "rainfall": f"{rainfall:.1f}",
                "image_status": image_status,
                "vision_confidence": f"{vision_confidence:.2f}",
                "uncertainty_case": uncertainty_case,
                **simulate_robot_pose(index),
            }
        )

    return rows


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = generate_rows()

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "timestamp",
                "temperature",
                "humidity",
                "soil_moisture",
                "light",
                "rainfall",
                "image_status",
                "vision_confidence",
                "uncertainty_case",
                "robot_x_m",
                "robot_y_m",
                "robot_heading_deg",
                "region_id",
                "path_segment",
                "patrol_loop",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} rows at {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
