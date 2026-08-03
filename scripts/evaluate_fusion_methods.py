from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from analyze_crop_risk import (
    CleanedRecord,
    FusionWeights,
    ProbabilityDistribution,
    RISK_SEVERITY,
    TREND_WINDOW_SIZE,
    assess_environment,
    assess_record,
    assess_uncertainty,
    assess_vision,
    clean_record,
    decide_safety_action,
    detect_conflicts,
    dominant_state,
    fuse_probabilities,
    probability_risk_score,
    read_input_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_OUTPUT_PATH = PROJECT_ROOT / "data" / "fusion_method_comparison.csv"
PREDICTION_OUTPUT_PATH = PROJECT_ROOT / "data" / "fusion_method_predictions.csv"


@dataclass(frozen=True)
class MethodPrediction:
    method: str
    timestamp: str
    reference_label: str
    predicted_label: str
    risk_score: float
    uncertainty_score: float
    uncertainty_detected: bool
    expected_uncertainty: bool
    conflict_detected: bool
    expected_conflict: bool
    anomaly_detected: bool
    expected_anomaly: bool
    action_permission: str
    safety_action: str


def infer_reference_label(record: CleanedRecord) -> str:
    candidates: list[tuple[float, str]] = []

    if record.anomaly_fields:
        candidates.append((RISK_SEVERITY["sensor_anomaly"], "sensor_anomaly"))
    if record.soil_moisture is not None and record.soil_moisture < 28:
        candidates.append((RISK_SEVERITY["drought"], "drought"))
    if (
        record.temperature is not None
        and "temperature" not in record.anomaly_fields
        and record.temperature > 34
    ):
        candidates.append((RISK_SEVERITY["heat"], "heat"))
    if (
        record.soil_moisture is not None
        and (
            record.soil_moisture > 58
            or (
                record.rainfall is not None
                and record.rainfall > 6
                and record.soil_moisture > 50
            )
        )
    ):
        candidates.append((RISK_SEVERITY["waterlogging"], "waterlogging"))
    if record.image_status == "pest" and record.vision_confidence >= 0.7:
        candidates.append((RISK_SEVERITY["pest"], "pest"))
    if (
        8 <= record.timestamp.hour <= 17
        and record.light is not None
        and record.light < 180
    ):
        candidates.append((RISK_SEVERITY["low_light"], "low_light"))

    if not candidates:
        return "healthy"

    return max(candidates, key=lambda item: item[0])[1]


def expected_conflict(record: CleanedRecord) -> bool:
    environment = assess_environment(record)
    vision = assess_vision(record)
    return bool(detect_conflicts(record, environment, vision))


def expected_uncertainty(record: CleanedRecord) -> bool:
    return (
        record.uncertainty_case != "normal"
        or bool(record.missing_fields)
        or bool(record.anomaly_fields)
        or record.vision_confidence < 0.5
        or expected_conflict(record)
    )


def make_prediction(
    method: str,
    record: CleanedRecord,
    predicted_label: str,
    risk_score: float,
    uncertainty_score: float,
    conflict_detected: bool,
    anomaly_detected: bool,
    action_permission: str,
    safety_action: str,
) -> MethodPrediction:
    return MethodPrediction(
        method=method,
        timestamp=record.timestamp_text,
        reference_label=infer_reference_label(record),
        predicted_label=predicted_label,
        risk_score=round(risk_score, 1),
        uncertainty_score=round(uncertainty_score, 1),
        uncertainty_detected=uncertainty_score >= 30,
        expected_uncertainty=expected_uncertainty(record),
        conflict_detected=conflict_detected,
        expected_conflict=expected_conflict(record),
        anomaly_detected=anomaly_detected,
        expected_anomaly=bool(record.anomaly_fields),
        action_permission=action_permission,
        safety_action=safety_action,
    )


def predict_rule_fusion(records: list[CleanedRecord]) -> list[MethodPrediction]:
    predictions: list[MethodPrediction] = []

    for record in records:
        environment = assess_environment(record)
        prediction_label = environment.dominant_risk
        risk_score = environment.score

        if record.image_status in {"drought", "pest", "waterlogging"} and record.vision_confidence >= 0.75:
            image_score = RISK_SEVERITY[record.image_status] * record.vision_confidence
            if image_score > risk_score:
                prediction_label = record.image_status
                risk_score = image_score

        uncertainty_score = 0.0
        if record.missing_fields:
            uncertainty_score += 25
        if record.anomaly_fields:
            uncertainty_score += 25
        if record.vision_confidence < 0.5:
            uncertainty_score += 20

        safety_decision = decide_safety_action(risk_score, uncertainty_score)
        predictions.append(
            make_prediction(
                method="rule_fusion",
                record=record,
                predicted_label=prediction_label,
                risk_score=risk_score,
                uncertainty_score=uncertainty_score,
                conflict_detected=False,
                anomaly_detected=bool(record.anomaly_fields),
                action_permission=safety_decision.action_permission,
                safety_action=safety_decision.safety_action,
            )
        )

    return predictions


def predict_fixed_weighted_fusion(records: list[CleanedRecord]) -> list[MethodPrediction]:
    predictions: list[MethodPrediction] = []
    fixed_weights = FusionWeights(
        sensor_weight=0.62,
        vision_weight=0.38,
        reliability_adjustments=(),
    )

    for record in records:
        environment = assess_environment(record)
        vision = assess_vision(record)
        conflicts = detect_conflicts(record, environment, vision)
        probabilities = fuse_probabilities(environment, vision, fixed_weights)
        risk_score = probability_risk_score(probabilities)
        if conflicts and max(environment.score, vision.score) >= 50:
            risk_score = max(risk_score, 45)
        predicted_label = dominant_state(probabilities, risk_score)
        state_confidence = probabilities[predicted_label]
        uncertainty_score = assess_uncertainty(
            record=record,
            conflicts=conflicts,
            state_confidence=state_confidence,
            consistency_flags=(),
        )
        safety_decision = decide_safety_action(risk_score, uncertainty_score)
        predictions.append(
            make_prediction(
                method="fixed_weighted_fusion",
                record=record,
                predicted_label=predicted_label,
                risk_score=risk_score,
                uncertainty_score=uncertainty_score,
                conflict_detected=bool(conflicts),
                anomaly_detected=bool(record.anomaly_fields),
                action_permission=safety_decision.action_permission,
                safety_action=safety_decision.safety_action,
            )
        )

    return predictions


def predict_uncertainty_weighted_fusion(records: list[CleanedRecord]) -> list[MethodPrediction]:
    predictions: list[MethodPrediction] = []
    previous_belief: ProbabilityDistribution | None = None

    for index, record in enumerate(records):
        window_start = max(0, index - TREND_WINDOW_SIZE + 1)
        temporal_window = records[window_start : index + 1]
        assessment, previous_belief = assess_record(
            record=record,
            temporal_window=temporal_window,
            previous_belief=previous_belief,
        )
        predictions.append(
            make_prediction(
                method="uncertainty_weighted_fusion",
                record=record,
                predicted_label=assessment.dominant_risk,
                risk_score=assessment.risk_score,
                uncertainty_score=assessment.uncertainty_score,
                conflict_detected=bool(assessment.conflict_flags),
                anomaly_detected=bool(record.anomaly_fields),
                action_permission=assessment.action_permission,
                safety_action=assessment.safety_action,
            )
        )

    return predictions


def rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def is_reference_risk(prediction: MethodPrediction) -> bool:
    return prediction.reference_label != "healthy"


def is_predicted_risk(prediction: MethodPrediction) -> bool:
    return prediction.predicted_label != "healthy" or prediction.risk_score >= 40


def is_risk_response(prediction: MethodPrediction) -> bool:
    return is_predicted_risk(prediction) or prediction.action_permission in {"execute", "hold"}


def is_clean_stable_sample(prediction: MethodPrediction) -> bool:
    return prediction.reference_label == "healthy" and not prediction.expected_uncertainty


def is_modality_degraded_sample(prediction: MethodPrediction) -> bool:
    return prediction.expected_uncertainty


def binary_risk_match(prediction: MethodPrediction) -> bool:
    return is_predicted_risk(prediction) == is_reference_risk(prediction)


def parse_timestamp(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, "%Y-%m-%d %H:%M")


def split_reference_risk_events(
    predictions: list[MethodPrediction],
) -> list[list[MethodPrediction]]:
    events: list[list[MethodPrediction]] = []
    current_event: list[MethodPrediction] = []

    for prediction in predictions:
        if is_reference_risk(prediction):
            current_event.append(prediction)
            continue
        if current_event:
            events.append(current_event)
            current_event = []

    if current_event:
        events.append(current_event)

    return events


def decision_latency_metrics(predictions: list[MethodPrediction]) -> tuple[float, float, float]:
    events = split_reference_risk_events(predictions)
    if not events:
        return 0.0, 0.0, 0.0

    latencies: list[float] = []
    missed_events = 0
    for event in events:
        first_response = next(
            (prediction for prediction in event if is_risk_response(prediction)),
            None,
        )
        if first_response is None:
            missed_events += 1
            continue

        event_start = parse_timestamp(event[0].timestamp)
        response_time = parse_timestamp(first_response.timestamp)
        latency_hours = (response_time - event_start).total_seconds() / 3600
        latencies.append(latency_hours)

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    worst_latency = max(latencies) if latencies else 0.0
    event_miss_rate = missed_events / len(events)
    return avg_latency, worst_latency, event_miss_rate


def build_summary_rows(predictions: Iterable[MethodPrediction]) -> list[dict[str, str]]:
    predictions_by_method: dict[str, list[MethodPrediction]] = {}
    for prediction in predictions:
        predictions_by_method.setdefault(prediction.method, []).append(prediction)

    rows: list[dict[str, str]] = []
    for method, method_predictions in predictions_by_method.items():
        total = len(method_predictions)
        exact_matches = sum(
            prediction.predicted_label == prediction.reference_label
            for prediction in method_predictions
        )
        binary_matches = sum(
            binary_risk_match(prediction) for prediction in method_predictions
        )
        true_risk_cases = [
            prediction for prediction in method_predictions if is_reference_risk(prediction)
        ]
        clean_stable_cases = [
            prediction for prediction in method_predictions if is_clean_stable_sample(prediction)
        ]
        degraded_cases = [
            prediction for prediction in method_predictions if is_modality_degraded_sample(prediction)
        ]
        clean_binary_matches = sum(
            binary_risk_match(prediction) for prediction in clean_stable_cases
        )
        degraded_binary_matches = sum(
            binary_risk_match(prediction) for prediction in degraded_cases
        )
        degraded_risk_cases = [
            prediction
            for prediction in degraded_cases
            if is_reference_risk(prediction) or prediction.risk_score >= 40
        ]
        uncertainty_cases = [
            prediction for prediction in method_predictions if prediction.expected_uncertainty
        ]
        conflict_cases = [
            prediction for prediction in method_predictions if prediction.expected_conflict
        ]
        anomaly_cases = [
            prediction for prediction in method_predictions if prediction.expected_anomaly
        ]
        uncertain_medium_or_high_risk = [
            prediction
            for prediction in method_predictions
            if prediction.expected_uncertainty and prediction.risk_score >= 40
        ]
        avg_latency, worst_latency, risk_event_miss_rate = decision_latency_metrics(
            method_predictions
        )
        clean_binary_accuracy = rate(clean_binary_matches, len(clean_stable_cases))
        degraded_binary_accuracy = rate(degraded_binary_matches, len(degraded_cases))
        degraded_uncertainty_detection = rate(
            sum(prediction.uncertainty_detected for prediction in degraded_cases),
            len(degraded_cases),
        )
        degraded_safe_response = rate(
            sum(prediction.action_permission != "execute" for prediction in degraded_risk_cases),
            len(degraded_risk_cases),
        )
        modality_degradation_robustness = (
            degraded_binary_accuracy
            + degraded_uncertainty_detection
            + degraded_safe_response
        ) / 3
        degraded_accuracy_retention = (
            degraded_binary_accuracy / clean_binary_accuracy
            if clean_binary_accuracy > 0
            else 0.0
        )
        risk_detection_recall = rate(
            sum(is_predicted_risk(prediction) for prediction in true_risk_cases),
            len(true_risk_cases),
        )
        risk_miss_rate = rate(
            sum(not is_predicted_risk(prediction) for prediction in true_risk_cases),
            len(true_risk_cases),
        )
        safety_false_triggers = sum(
            prediction.action_permission != "observe"
            or prediction.safety_action != "routine_patrol"
            or is_predicted_risk(prediction)
            for prediction in clean_stable_cases
        )
        safety_false_trigger_rate = rate(safety_false_triggers, len(clean_stable_cases))

        rows.append(
            {
                "method": method,
                "samples": str(total),
                "risk_class_accuracy": f"{rate(exact_matches, total):.3f}",
                "binary_risk_accuracy": f"{rate(binary_matches, total):.3f}",
                "risk_detection_recall": f"{risk_detection_recall:.3f}",
                "risk_miss_rate": f"{risk_miss_rate:.3f}",
                "avg_decision_latency_hours": f"{avg_latency:.2f}",
                "worst_decision_latency_hours": f"{worst_latency:.2f}",
                "risk_event_miss_rate": f"{risk_event_miss_rate:.3f}",
                "safety_false_trigger_rate": f"{safety_false_trigger_rate:.3f}",
                "degraded_binary_risk_accuracy": f"{degraded_binary_accuracy:.3f}",
                "degraded_uncertainty_detection_rate": f"{degraded_uncertainty_detection:.3f}",
                "degraded_safe_response_rate": f"{degraded_safe_response:.3f}",
                "modality_degradation_robustness": f"{modality_degradation_robustness:.3f}",
                "degraded_accuracy_retention": f"{degraded_accuracy_retention:.3f}",
                "uncertainty_detection_rate": f"{rate(sum(p.uncertainty_detected for p in uncertainty_cases), len(uncertainty_cases)):.3f}",
                "conflict_detection_rate": f"{rate(sum(p.conflict_detected for p in conflict_cases), len(conflict_cases)):.3f}",
                "anomaly_detection_rate": f"{rate(sum(p.anomaly_detected for p in anomaly_cases), len(anomaly_cases)):.3f}",
                "safe_hold_rate_on_uncertain_risk": f"{rate(sum(p.action_permission != 'execute' for p in uncertain_medium_or_high_risk), len(uncertain_medium_or_high_risk)):.3f}",
            }
        )

    return rows


def write_predictions(predictions: list[MethodPrediction]) -> None:
    PREDICTION_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PREDICTION_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "method",
                "timestamp",
                "reference_label",
                "predicted_label",
                "risk_score",
                "uncertainty_score",
                "uncertainty_detected",
                "expected_uncertainty",
                "conflict_detected",
                "expected_conflict",
                "anomaly_detected",
                "expected_anomaly",
                "action_permission",
                "safety_action",
            ],
        )
        writer.writeheader()
        for prediction in predictions:
            writer.writerow(
                {
                    "method": prediction.method,
                    "timestamp": prediction.timestamp,
                    "reference_label": prediction.reference_label,
                    "predicted_label": prediction.predicted_label,
                    "risk_score": f"{prediction.risk_score:.1f}",
                    "uncertainty_score": f"{prediction.uncertainty_score:.1f}",
                    "uncertainty_detected": str(prediction.uncertainty_detected),
                    "expected_uncertainty": str(prediction.expected_uncertainty),
                    "conflict_detected": str(prediction.conflict_detected),
                    "expected_conflict": str(prediction.expected_conflict),
                    "anomaly_detected": str(prediction.anomaly_detected),
                    "expected_anomaly": str(prediction.expected_anomaly),
                    "action_permission": prediction.action_permission,
                    "safety_action": prediction.safety_action,
                }
            )


def write_summary(rows: list[dict[str, str]]) -> None:
    SUMMARY_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "method",
                "samples",
                "risk_class_accuracy",
                "binary_risk_accuracy",
                "risk_detection_recall",
                "risk_miss_rate",
                "avg_decision_latency_hours",
                "worst_decision_latency_hours",
                "risk_event_miss_rate",
                "safety_false_trigger_rate",
                "degraded_binary_risk_accuracy",
                "degraded_uncertainty_detection_rate",
                "degraded_safe_response_rate",
                "modality_degradation_robustness",
                "degraded_accuracy_retention",
                "uncertainty_detection_rate",
                "conflict_detection_rate",
                "anomaly_detection_rate",
                "safe_hold_rate_on_uncertain_risk",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    records = sorted(
        (clean_record(row) for row in read_input_rows()),
        key=lambda record: record.timestamp,
    )
    predictions = (
        predict_rule_fusion(records)
        + predict_fixed_weighted_fusion(records)
        + predict_uncertainty_weighted_fusion(records)
    )
    summary_rows = build_summary_rows(predictions)

    write_predictions(predictions)
    write_summary(summary_rows)

    print(f"Generated comparison summary at {SUMMARY_OUTPUT_PATH}")
    print(f"Generated per-sample predictions at {PREDICTION_OUTPUT_PATH}")
    for row in summary_rows:
        print(
            row["method"],
            "risk_class_accuracy=" + row["risk_class_accuracy"],
            "risk_miss_rate=" + row["risk_miss_rate"],
            "avg_decision_latency_hours=" + row["avg_decision_latency_hours"],
            "safety_false_trigger_rate=" + row["safety_false_trigger_rate"],
            "modality_degradation_robustness=" + row["modality_degradation_robustness"],
            "uncertainty_detection_rate=" + row["uncertainty_detection_rate"],
            "safe_hold_rate_on_uncertain_risk=" + row["safe_hold_rate_on_uncertain_risk"],
        )


if __name__ == "__main__":
    main()
