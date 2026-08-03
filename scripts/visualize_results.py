from __future__ import annotations

import csv
from html import escape
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RISK_RESULTS_PATH = PROJECT_ROOT / "data" / "risk_assessment_results.csv"
COMPARISON_PATH = PROJECT_ROOT / "data" / "fusion_method_comparison.csv"
SPATIOTEMPORAL_MAP_PATH = PROJECT_ROOT / "data" / "spatiotemporal_risk_map.csv"
SPATIAL_OBSERVATIONS_PATH = PROJECT_ROOT / "data" / "spatial_risk_observations.csv"
FIGURE_DIR = PROJECT_ROOT / "figures"

CHART_WIDTH = 1200
CHART_HEIGHT = 520
MARGIN_LEFT = 82
MARGIN_RIGHT = 36
MARGIN_TOP = 62
MARGIN_BOTTOM = 76

STATE_COLORS = {
    "p_healthy": "#2e7d32",
    "p_drought": "#ef6c00",
    "p_heat": "#c62828",
    "p_pest": "#6a1b9a",
    "p_waterlogging": "#1565c0",
    "p_low_light": "#f9a825",
    "p_sensor_anomaly": "#455a64",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def scale_x(index: int, count: int) -> float:
    plot_width = CHART_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    if count <= 1:
        return MARGIN_LEFT
    return MARGIN_LEFT + index / (count - 1) * plot_width


def scale_y(value: float, minimum: float, maximum: float) -> float:
    plot_height = CHART_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
    normalized = (value - minimum) / (maximum - minimum)
    return MARGIN_TOP + (1 - normalized) * plot_height


def make_polyline(values: list[float], minimum: float, maximum: float) -> str:
    return " ".join(
        f"{scale_x(index, len(values)):.1f},{scale_y(value, minimum, maximum):.1f}"
        for index, value in enumerate(values)
    )


def grid_lines(minimum: float, maximum: float, step: float) -> str:
    elements: list[str] = []
    value = minimum
    while value <= maximum + 1e-9:
        y = scale_y(value, minimum, maximum)
        elements.append(
            f'<line x1="{MARGIN_LEFT}" y1="{y:.1f}" x2="{CHART_WIDTH - MARGIN_RIGHT}" '
            f'y2="{y:.1f}" stroke="#e0e0e0" stroke-width="1" />'
        )
        elements.append(
            f'<text x="{MARGIN_LEFT - 12}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="12" fill="#555">{value:g}</text>'
        )
        value += step
    return "\n".join(elements)


def marker_lines(rows: list[dict[str, str]], minimum: float, maximum: float) -> str:
    markers: list[str] = []
    for index, row in enumerate(rows):
        case = row.get("uncertainty_case", "normal")
        if case == "normal":
            continue
        x = scale_x(index, len(rows))
        markers.append(
            f'<line x1="{x:.1f}" y1="{MARGIN_TOP}" x2="{x:.1f}" '
            f'y2="{CHART_HEIGHT - MARGIN_BOTTOM}" stroke="#616161" '
            f'stroke-dasharray="5 5" stroke-width="1.2" />'
        )
        markers.append(
            f'<text x="{x + 5:.1f}" y="{scale_y(maximum, minimum, maximum) + 14:.1f}" '
            f'font-size="11" fill="#424242" transform="rotate(30 {x + 5:.1f} '
            f'{scale_y(maximum, minimum, maximum) + 14:.1f})">{escape(case)}</text>'
        )
    return "\n".join(markers)


def legend(items: list[tuple[str, str]], start_x: int = 92, start_y: int = 28) -> str:
    elements: list[str] = []
    x = start_x
    y = start_y
    for label, color in items:
        elements.append(
            f'<rect x="{x}" y="{y - 10}" width="14" height="14" fill="{color}" rx="2" />'
        )
        elements.append(
            f'<text x="{x + 20}" y="{y + 2}" font-size="13" fill="#333">{escape(label)}</text>'
        )
        x += max(110, len(label) * 8 + 44)
        if x > CHART_WIDTH - 180:
            x = start_x
            y += 22
    return "\n".join(elements)


def line_chart(
    *,
    title: str,
    rows: list[dict[str, str]],
    series: list[tuple[str, list[float], str]],
    minimum: float,
    maximum: float,
    step: float,
    output_path: Path,
    y_label: str,
    threshold_lines: list[tuple[float, str, str]] | None = None,
) -> None:
    start_time = rows[0]["timestamp"]
    end_time = rows[-1]["timestamp"]
    threshold_lines = threshold_lines or []

    polylines = []
    for label, values, color in series:
        polylines.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2.2" '
            f'points="{make_polyline(values, minimum, maximum)}" />'
        )

    thresholds = []
    for value, label, color in threshold_lines:
        y = scale_y(value, minimum, maximum)
        thresholds.append(
            f'<line x1="{MARGIN_LEFT}" y1="{y:.1f}" x2="{CHART_WIDTH - MARGIN_RIGHT}" '
            f'y2="{y:.1f}" stroke="{color}" stroke-dasharray="6 4" stroke-width="1.3" />'
        )
        thresholds.append(
            f'<text x="{CHART_WIDTH - MARGIN_RIGHT - 6}" y="{y - 5:.1f}" text-anchor="end" '
            f'font-size="12" fill="{color}">{escape(label)}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CHART_WIDTH}" height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}">
<rect width="100%" height="100%" fill="#ffffff" />
<text x="{CHART_WIDTH / 2:.1f}" y="24" text-anchor="middle" font-size="20" font-weight="700" fill="#222">{escape(title)}</text>
{legend([(label, color) for label, _, color in series])}
<rect x="{MARGIN_LEFT}" y="{MARGIN_TOP}" width="{CHART_WIDTH - MARGIN_LEFT - MARGIN_RIGHT}" height="{CHART_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM}" fill="#fafafa" stroke="#bdbdbd" />
{grid_lines(minimum, maximum, step)}
{marker_lines(rows, minimum, maximum)}
{''.join(thresholds)}
{''.join(polylines)}
<text x="{MARGIN_LEFT}" y="{CHART_HEIGHT - 34}" font-size="12" fill="#555">{escape(start_time)}</text>
<text x="{CHART_WIDTH - MARGIN_RIGHT}" y="{CHART_HEIGHT - 34}" text-anchor="end" font-size="12" fill="#555">{escape(end_time)}</text>
<text x="{CHART_WIDTH / 2:.1f}" y="{CHART_HEIGHT - 14}" text-anchor="middle" font-size="13" fill="#555">time</text>
<text x="22" y="{CHART_HEIGHT / 2:.1f}" text-anchor="middle" font-size="13" fill="#555" transform="rotate(-90 22 {CHART_HEIGHT / 2:.1f})">{escape(y_label)}</text>
</svg>
"""
    output_path.write_text(svg, encoding="utf-8")


def bar_chart(rows: list[dict[str, str]], output_path: Path) -> None:
    metrics = [
        ("risk_class_accuracy", "#5e35b1"),
        ("uncertainty_detection_rate", "#00897b"),
        ("safe_hold_rate_on_uncertain_risk", "#d81b60"),
    ]
    methods = [row["method"] for row in rows]
    plot_width = CHART_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    plot_height = CHART_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
    group_width = plot_width / len(methods)
    bar_width = group_width / (len(metrics) + 1)
    elements: list[str] = []

    for method_index, row in enumerate(rows):
        group_x = MARGIN_LEFT + method_index * group_width
        for metric_index, (metric, color) in enumerate(metrics):
            value = float(row[metric])
            height = value * plot_height
            x = group_x + (metric_index + 0.5) * bar_width
            y = MARGIN_TOP + plot_height - height
            elements.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width * 0.8:.1f}" height="{height:.1f}" '
                f'fill="{color}" rx="3" />'
            )
            elements.append(
                f'<text x="{x + bar_width * 0.4:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                f'font-size="12" fill="#333">{value:.3f}</text>'
            )
        elements.append(
            f'<text x="{group_x + group_width / 2:.1f}" y="{CHART_HEIGHT - 38}" '
            f'text-anchor="middle" font-size="12" fill="#333">{escape(row["method"])}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CHART_WIDTH}" height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}">
<rect width="100%" height="100%" fill="#ffffff" />
<text x="{CHART_WIDTH / 2:.1f}" y="24" text-anchor="middle" font-size="20" font-weight="700" fill="#222">Fusion Method Comparison</text>
{legend([(metric, color) for metric, color in metrics])}
<rect x="{MARGIN_LEFT}" y="{MARGIN_TOP}" width="{plot_width}" height="{plot_height}" fill="#fafafa" stroke="#bdbdbd" />
{grid_lines(0, 1, 0.2)}
{''.join(elements)}
<text x="22" y="{CHART_HEIGHT / 2:.1f}" text-anchor="middle" font-size="13" fill="#555" transform="rotate(-90 22 {CHART_HEIGHT / 2:.1f})">score</text>
</svg>
"""
    output_path.write_text(svg, encoding="utf-8")


def risk_color(score: float) -> str:
    if score >= 80:
        return "#b71c1c"
    if score >= 60:
        return "#ef6c00"
    if score >= 40:
        return "#fdd835"
    if score >= 20:
        return "#9ccc65"
    return "#2e7d32"


def spatial_x(value: float, field_width: float, map_left: float, map_width: float) -> float:
    return map_left + value / field_width * map_width


def spatial_y(value: float, field_height: float, map_top: float, map_height: float) -> float:
    return map_top + map_height - value / field_height * map_height


def spatiotemporal_map_chart(
    region_rows: list[dict[str, str]],
    observations: list[dict[str, str]],
    output_path: Path,
) -> None:
    width = 1200
    height = 760
    map_left = 88
    map_top = 76
    map_width = 920
    map_height = 600
    max_grid_row = max(int(row["grid_row"]) for row in region_rows)
    max_grid_column = max(int(row["grid_column"]) for row in region_rows)
    center_x_values = [float(row["center_x_m"]) for row in region_rows]
    center_y_values = [float(row["center_y_m"]) for row in region_rows]
    cell_width_m = (max(center_x_values) - min(center_x_values)) / (max_grid_column - 1)
    cell_height_m = (max(center_y_values) - min(center_y_values)) / (max_grid_row - 1)
    field_width = max(center_x_values) + cell_width_m / 2
    field_height = max(center_y_values) + cell_height_m / 2
    cell_width = map_width / max_grid_column
    cell_height = map_height / max_grid_row

    cell_elements: list[str] = []
    for row in region_rows:
        grid_row = int(row["grid_row"])
        grid_column = int(row["grid_column"])
        avg_risk = float(row["avg_risk_score"])
        max_risk = float(row["max_risk_score"])
        x = map_left + (grid_column - 1) * cell_width
        y = map_top + (max_grid_row - grid_row) * cell_height
        fill = risk_color(avg_risk)
        text_color = "#ffffff" if avg_risk >= 60 else "#1b1b1b"
        cell_elements.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_width:.1f}" '
            f'height="{cell_height:.1f}" fill="{fill}" stroke="#ffffff" stroke-width="2" />'
        )
        cell_elements.append(
            f'<text x="{x + cell_width / 2:.1f}" y="{y + 36:.1f}" text-anchor="middle" '
            f'font-size="15" font-weight="700" fill="{text_color}">{escape(row["region_id"])}</text>'
        )
        cell_elements.append(
            f'<text x="{x + cell_width / 2:.1f}" y="{y + 58:.1f}" text-anchor="middle" '
            f'font-size="12" fill="{text_color}">avg {avg_risk:.1f} / max {max_risk:.1f}</text>'
        )
        cell_elements.append(
            f'<text x="{x + cell_width / 2:.1f}" y="{y + 78:.1f}" text-anchor="middle" '
            f'font-size="12" fill="{text_color}">{escape(row["peak_dominant_risk"])}</text>'
        )
        cell_elements.append(
            f'<text x="{x + cell_width / 2:.1f}" y="{y + 98:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{text_color}">{escape(row.get("most_common_robot_action_mode", "continue_patrol"))}</text>'
        )

    path_step = max(1, len(observations) // 240)
    path_points = " ".join(
        f'{spatial_x(float(row["robot_x_m"]), field_width, map_left, map_width):.1f},'
        f'{spatial_y(float(row["robot_y_m"]), field_height, map_top, map_height):.1f}'
        for row in observations[::path_step]
    )
    uncertainty_markers: list[str] = []
    for row in observations:
        if row["uncertainty_case"] == "normal":
            continue
        x = spatial_x(float(row["robot_x_m"]), field_width, map_left, map_width)
        y = spatial_y(float(row["robot_y_m"]), field_height, map_top, map_height)
        uncertainty_markers.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="#000000" stroke="#ffffff" stroke-width="2" />'
        )
        uncertainty_markers.append(
            f'<text x="{x + 10:.1f}" y="{y - 8:.1f}" font-size="11" fill="#212121">{escape(row["uncertainty_case"])}</text>'
        )

    legend_x = 1035
    legend_y = 110
    legend_items = [
        ("very low", 10),
        ("low", 30),
        ("medium", 50),
        ("medium-high", 70),
        ("high", 90),
    ]
    legend_elements = []
    for index, (label, score) in enumerate(legend_items):
        y = legend_y + index * 30
        legend_elements.append(
            f'<rect x="{legend_x}" y="{y}" width="24" height="18" fill="{risk_color(score)}" />'
        )
        legend_elements.append(
            f'<text x="{legend_x + 32}" y="{y + 14}" font-size="13" fill="#333">{escape(label)}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#ffffff" />
<text x="{width / 2:.1f}" y="28" text-anchor="middle" font-size="22" font-weight="700" fill="#222">Spatiotemporal Risk Map</text>
<text x="{map_left}" y="56" font-size="13" fill="#555">Cell color = average HMM risk score; labels show avg/max risk, peak dominant risk, and common robot action.</text>
<rect x="{map_left}" y="{map_top}" width="{map_width}" height="{map_height}" fill="#fafafa" stroke="#9e9e9e" />
{''.join(cell_elements)}
<polyline fill="none" stroke="#212121" stroke-width="2.0" stroke-opacity="0.55" points="{path_points}" />
{''.join(uncertainty_markers)}
<text x="{legend_x}" y="{legend_y - 22}" font-size="15" font-weight="700" fill="#333">Avg risk</text>
{''.join(legend_elements)}
<line x1="{legend_x}" y1="{legend_y + 178}" x2="{legend_x + 36}" y2="{legend_y + 178}" stroke="#212121" stroke-width="2" stroke-opacity="0.55" />
<text x="{legend_x + 46}" y="{legend_y + 182}" font-size="13" fill="#333">robot path</text>
<circle cx="{legend_x + 12}" cy="{legend_y + 212}" r="7" fill="#000000" stroke="#ffffff" stroke-width="2" />
<text x="{legend_x + 46}" y="{legend_y + 216}" font-size="13" fill="#333">uncertainty case</text>
<text x="{map_left + map_width / 2:.1f}" y="{height - 28}" text-anchor="middle" font-size="13" fill="#555">field x coordinate</text>
<text x="24" y="{map_top + map_height / 2:.1f}" text-anchor="middle" font-size="13" fill="#555" transform="rotate(-90 24 {map_top + map_height / 2:.1f})">field y coordinate</text>
</svg>
"""
    output_path.write_text(svg, encoding="utf-8")


def main() -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    risk_rows = read_csv(RISK_RESULTS_PATH)
    comparison_rows = read_csv(COMPARISON_PATH)
    region_rows = read_csv(SPATIOTEMPORAL_MAP_PATH)
    spatial_observations = read_csv(SPATIAL_OBSERVATIONS_PATH)

    risk_scores = [float(row["risk_score"]) for row in risk_rows]
    uncertainty_scores = [float(row["uncertainty_score"]) for row in risk_rows]
    state_series = [
        (state.removeprefix("p_"), [float(row[state]) for row in risk_rows], color)
        for state, color in STATE_COLORS.items()
    ]

    line_chart(
        title="Risk Score Over Time",
        rows=risk_rows,
        series=[("risk_score", risk_scores, "#c62828")],
        minimum=0,
        maximum=100,
        step=20,
        output_path=FIGURE_DIR / "risk_curve.svg",
        y_label="risk score",
        threshold_lines=[
            (40, "medium risk", "#ef6c00"),
            (60, "medium-high risk", "#c62828"),
        ],
    )
    line_chart(
        title="State Probability Curves",
        rows=risk_rows,
        series=state_series,
        minimum=0,
        maximum=1,
        step=0.2,
        output_path=FIGURE_DIR / "state_probability_curves.svg",
        y_label="probability",
    )
    line_chart(
        title="Uncertainty Score Over Time",
        rows=risk_rows,
        series=[("uncertainty_score", uncertainty_scores, "#1565c0")],
        minimum=0,
        maximum=100,
        step=20,
        output_path=FIGURE_DIR / "uncertainty_curve.svg",
        y_label="uncertainty score",
        threshold_lines=[
            (30, "medium uncertainty", "#ef6c00"),
            (70, "high uncertainty", "#c62828"),
        ],
    )
    bar_chart(comparison_rows, FIGURE_DIR / "fusion_method_comparison.svg")
    spatiotemporal_map_chart(
        region_rows,
        spatial_observations,
        FIGURE_DIR / "spatiotemporal_risk_map.svg",
    )

    print(f"Generated SVG figures in {FIGURE_DIR}")


if __name__ == "__main__":
    main()
