from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOCK_DATA_PATH = PROJECT_ROOT / "data" / "mock_environment_data.csv"
RISK_RESULTS_PATH = PROJECT_ROOT / "data" / "risk_assessment_results.csv"
OBSERVATION_OUTPUT_PATH = PROJECT_ROOT / "data" / "spatial_risk_observations.csv"
MAP_OUTPUT_PATH = PROJECT_ROOT / "data" / "spatiotemporal_risk_map.csv"

REQUIRED_MOCK_COLUMNS = {
    "timestamp",
    "robot_x_m",
    "robot_y_m",
    "robot_heading_deg",
    "region_id",
    "path_segment",
    "patrol_loop",
}
REQUIRED_RISK_COLUMNS = {
    "timestamp",
    "risk_score",
    "risk_level",
    "state_confidence",
    "uncertainty_score",
    "uncertainty_level",
    "dominant_risk",
    "action_permission",
    "safety_action",
    "safety_policy",
}


def read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")

    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"Empty CSV file: {path}")
        missing_columns = required_columns - set(reader.fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"{path} is missing required columns: {missing}")
        return list(reader)


def parse_float(row: dict[str, str], field: str) -> float:
    try:
        return float(row[field])
    except ValueError as error:
        raise ValueError(f"Invalid float in {field}: {row[field]}") from error


def parse_region_id(region_id: str) -> tuple[int, int]:
    try:
        row_part, column_part = region_id.split("C")
        grid_row = int(row_part.removeprefix("R"))
        grid_column = int(column_part)
    except ValueError as error:
        raise ValueError(f"Invalid region_id: {region_id}") from error

    return grid_row, grid_column


def join_observations() -> list[dict[str, str]]:
    mock_rows = read_csv(MOCK_DATA_PATH, REQUIRED_MOCK_COLUMNS)
    risk_rows = read_csv(RISK_RESULTS_PATH, REQUIRED_RISK_COLUMNS)
    risk_by_timestamp = {row["timestamp"]: row for row in risk_rows}

    observations: list[dict[str, str]] = []
    for mock_row in mock_rows:
        timestamp = mock_row["timestamp"]
        if timestamp not in risk_by_timestamp:
            raise ValueError(f"Missing risk result for timestamp: {timestamp}")
        risk_row = risk_by_timestamp[timestamp]
        grid_row, grid_column = parse_region_id(mock_row["region_id"])
        observations.append(
            {
                "timestamp": timestamp,
                "robot_x_m": mock_row["robot_x_m"],
                "robot_y_m": mock_row["robot_y_m"],
                "robot_heading_deg": mock_row["robot_heading_deg"],
                "region_id": mock_row["region_id"],
                "grid_row": str(grid_row),
                "grid_column": str(grid_column),
                "path_segment": mock_row["path_segment"],
                "patrol_loop": mock_row["patrol_loop"],
                "risk_score": risk_row["risk_score"],
                "risk_level": risk_row["risk_level"],
                "state_confidence": risk_row["state_confidence"],
                "uncertainty_score": risk_row["uncertainty_score"],
                "uncertainty_level": risk_row["uncertainty_level"],
                "dominant_risk": risk_row["dominant_risk"],
                "action_permission": risk_row["action_permission"],
                "safety_action": risk_row["safety_action"],
                "safety_policy": risk_row["safety_policy"],
                "uncertainty_case": mock_row["uncertainty_case"],
            }
        )

    return observations


def write_observations(observations: list[dict[str, str]]) -> None:
    OBSERVATION_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OBSERVATION_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(observations[0].keys()))
        writer.writeheader()
        writer.writerows(observations)


def average(values: list[float]) -> float:
    return sum(values) / len(values)


def build_region_rows(observations: list[dict[str, str]]) -> list[dict[str, str]]:
    by_region: dict[str, list[dict[str, str]]] = defaultdict(list)
    for observation in observations:
        by_region[observation["region_id"]].append(observation)

    region_rows: list[dict[str, str]] = []
    for region_id, region_observations in by_region.items():
        ordered = sorted(region_observations, key=lambda row: row["timestamp"])
        risk_scores = [parse_float(row, "risk_score") for row in ordered]
        uncertainty_scores = [parse_float(row, "uncertainty_score") for row in ordered]
        x_values = [parse_float(row, "robot_x_m") for row in ordered]
        y_values = [parse_float(row, "robot_y_m") for row in ordered]
        peak_observation = max(ordered, key=lambda row: parse_float(row, "risk_score"))
        latest_observation = ordered[-1]
        risk_observations = [score for score in risk_scores if score >= 40]
        high_uncertainty_observations = [
            score for score in uncertainty_scores if score >= 30
        ]
        action_counter = Counter(row["safety_action"] for row in ordered)
        dominant_counter = Counter(row["dominant_risk"] for row in ordered)

        region_rows.append(
            {
                "region_id": region_id,
                "grid_row": latest_observation["grid_row"],
                "grid_column": latest_observation["grid_column"],
                "center_x_m": f"{average(x_values):.1f}",
                "center_y_m": f"{average(y_values):.1f}",
                "sample_count": str(len(ordered)),
                "first_seen_timestamp": ordered[0]["timestamp"],
                "last_seen_timestamp": latest_observation["timestamp"],
                "avg_risk_score": f"{average(risk_scores):.1f}",
                "max_risk_score": f"{max(risk_scores):.1f}",
                "risk_observation_rate": f"{len(risk_observations) / len(ordered):.3f}",
                "avg_uncertainty_score": f"{average(uncertainty_scores):.1f}",
                "high_uncertainty_rate": f"{len(high_uncertainty_observations) / len(ordered):.3f}",
                "dominant_risk_mode": dominant_counter.most_common(1)[0][0],
                "peak_dominant_risk": peak_observation["dominant_risk"],
                "latest_risk_level": latest_observation["risk_level"],
                "latest_safety_action": latest_observation["safety_action"],
                "most_common_safety_action": action_counter.most_common(1)[0][0],
            }
        )

    return sorted(
        region_rows,
        key=lambda row: (int(row["grid_row"]), int(row["grid_column"])),
    )


def write_region_map(region_rows: list[dict[str, str]]) -> None:
    MAP_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MAP_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(region_rows[0].keys()))
        writer.writeheader()
        writer.writerows(region_rows)


def main() -> None:
    observations = join_observations()
    region_rows = build_region_rows(observations)
    write_observations(observations)
    write_region_map(region_rows)

    print(f"Generated {len(observations)} spatial observations at {OBSERVATION_OUTPUT_PATH}")
    print(f"Generated {len(region_rows)} region risk cells at {MAP_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
