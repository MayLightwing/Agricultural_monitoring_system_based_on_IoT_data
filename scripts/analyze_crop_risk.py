from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = PROJECT_ROOT / "data" / "mock_environment_data.csv"
OUTPUT_PATH = PROJECT_ROOT / "data" / "risk_assessment_results.csv"

REQUIRED_COLUMNS = {
    "timestamp",
    "temperature",
    "humidity",
    "soil_moisture",
    "light",
    "rainfall",
    "image_status",
    "vision_confidence",
    "uncertainty_case",
}
IMAGE_STATUSES = {"healthy", "drought", "pest", "waterlogging", "unknown"}
STATE_LABELS = (
    "healthy",
    "drought",
    "heat",
    "pest",
    "waterlogging",
    "low_light",
    "sensor_anomaly",
)
RISK_SEVERITY = {
    "healthy": 8,
    "drought": 82,
    "heat": 76,
    "pest": 72,
    "waterlogging": 78,
    "low_light": 46,
    "sensor_anomaly": 60,
}
TREND_WINDOW_SIZE = 6
EMA_ALPHA = 0.42

ProbabilityDistribution = dict[str, float]


@dataclass(frozen=True)
class CleanedRecord:
    timestamp: datetime
    timestamp_text: str
    temperature: float | None
    humidity: float | None
    soil_moisture: float | None
    light: float | None
    rainfall: float | None
    image_status: str
    vision_confidence: float
    uncertainty_case: str
    missing_fields: tuple[str, ...]
    anomaly_fields: tuple[str, ...]


@dataclass(frozen=True)
class ModalityAssessment:
    score: float
    dominant_risk: str
    reliability: float
    probabilities: ProbabilityDistribution
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FusionWeights:
    sensor_weight: float
    vision_weight: float
    reliability_adjustments: tuple[str, ...]


@dataclass(frozen=True)
class SafetyDecision:
    action_permission: str
    safety_action: str
    safety_policy: str


@dataclass(frozen=True)
class RiskAssessment:
    timestamp: str
    risk_score: float
    risk_level: str
    state_confidence: float
    uncertainty_score: float
    uncertainty_level: str
    dominant_risk: str
    sensor_score: float
    vision_score: float
    sensor_reliability: float
    vision_reliability: float
    dynamic_sensor_weight: float
    dynamic_vision_weight: float
    reliability_adjustments: tuple[str, ...]
    sensor_probabilities: ProbabilityDistribution
    vision_probabilities: ProbabilityDistribution
    fused_probabilities: ProbabilityDistribution
    smoothed_probabilities: ProbabilityDistribution
    trend_flags: tuple[str, ...]
    consistency_flags: tuple[str, ...]
    conflict_flags: tuple[str, ...]
    action_permission: str
    safety_action: str
    safety_policy: str
    reasons: tuple[str, ...]
    recommendation: str
    uncertainty_case: str


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def normalize_distribution(distribution: ProbabilityDistribution) -> ProbabilityDistribution:
    normalized = {
        state: max(0.0, distribution.get(state, 0.0))
        for state in STATE_LABELS
    }
    total = sum(normalized.values())
    if total <= 0:
        return {state: 1.0 if state == "healthy" else 0.0 for state in STATE_LABELS}

    return {state: value / total for state, value in normalized.items()}


def probability_risk_score(probabilities: ProbabilityDistribution) -> float:
    return sum(probabilities[state] * RISK_SEVERITY[state] for state in STATE_LABELS)


def dominant_state(probabilities: ProbabilityDistribution, risk_score: float) -> str:
    top_state = max(STATE_LABELS, key=lambda state: probabilities[state])
    if top_state == "healthy" and risk_score >= 40:
        risk_states = [state for state in STATE_LABELS if state != "healthy"]
        return max(risk_states, key=lambda state: probabilities[state])
    return top_state


def format_probabilities(probabilities: ProbabilityDistribution) -> str:
    return "；".join(
        f"P({state})={probabilities[state]:.2f}"
        for state in STATE_LABELS
    )


def parse_float(row: dict[str, str], field: str) -> float | None:
    value = row[field].strip()
    if value == "":
        return None

    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"字段 {field} 的数值无效: {value}") from error


def clean_record(row: dict[str, str]) -> CleanedRecord:
    timestamp_text = row["timestamp"].strip()
    try:
        timestamp = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise ValueError(f"timestamp 格式无效: {timestamp_text}") from error

    temperature = parse_float(row, "temperature")
    humidity = parse_float(row, "humidity")
    soil_moisture = parse_float(row, "soil_moisture")
    light = parse_float(row, "light")
    rainfall = parse_float(row, "rainfall")
    vision_confidence = parse_float(row, "vision_confidence")
    if vision_confidence is None or not 0 <= vision_confidence <= 1:
        raise ValueError(f"vision_confidence 必须在 0-1 之间: {row['vision_confidence']}")

    image_status = row["image_status"].strip()
    if image_status not in IMAGE_STATUSES:
        raise ValueError(f"未知 image_status: {image_status}")

    numeric_values = {
        "temperature": temperature,
        "humidity": humidity,
        "soil_moisture": soil_moisture,
        "light": light,
        "rainfall": rainfall,
    }
    missing_fields = tuple(field for field, value in numeric_values.items() if value is None)

    anomaly_fields: list[str] = []
    if temperature is not None and not 0 <= temperature <= 45:
        anomaly_fields.append("temperature")
    if humidity is not None and not 0 <= humidity <= 100:
        anomaly_fields.append("humidity")
    if soil_moisture is not None and not 0 <= soil_moisture <= 100:
        anomaly_fields.append("soil_moisture")
    if light is not None and not 0 <= light <= 1000:
        anomaly_fields.append("light")
    if rainfall is not None and not 0 <= rainfall <= 50:
        anomaly_fields.append("rainfall")

    return CleanedRecord(
        timestamp=timestamp,
        timestamp_text=timestamp_text,
        temperature=temperature,
        humidity=humidity,
        soil_moisture=soil_moisture,
        light=light,
        rainfall=rainfall,
        image_status=image_status,
        vision_confidence=vision_confidence,
        uncertainty_case=row["uncertainty_case"].strip(),
        missing_fields=missing_fields,
        anomaly_fields=tuple(anomaly_fields),
    )


def assess_environment(record: CleanedRecord) -> ModalityAssessment:
    candidates: list[tuple[float, str, str]] = []
    reasons: list[str] = []
    evidence = {state: 0.05 for state in STATE_LABELS}
    evidence["healthy"] = 1.0

    def add_evidence(state: str, strength: float, score: float, reason: str) -> None:
        evidence[state] += strength
        candidates.append((score, state, reason))

    if record.soil_moisture is None:
        reasons.append("土壤湿度缺失，无法直接判断根区缺水程度")
    elif record.soil_moisture < 18:
        add_evidence("drought", 5.4, 86, "土壤湿度严重偏低")
    elif record.soil_moisture < 28:
        add_evidence("drought", 3.2, 64, "土壤湿度偏低")
    elif record.soil_moisture > 58:
        add_evidence("waterlogging", 3.6, 70, "土壤湿度过高")

    temperature_is_usable = (
        record.temperature is not None and "temperature" not in record.anomaly_fields
    )
    if record.temperature is None:
        reasons.append("温度缺失，无法判断高温或低温压力")
    elif not temperature_is_usable:
        add_evidence("sensor_anomaly", 4.5, 58, "温度出现异常尖峰，疑似传感器噪声")
    elif record.temperature > 38:
        add_evidence("heat", 4.8, 82, "温度过高，存在热胁迫风险")
    elif record.temperature > 34:
        add_evidence("heat", 2.8, 62, "温度偏高")
    if "temperature" in record.anomaly_fields:
        reasons.append("温度出现异常尖峰，疑似传感器噪声")

    if record.humidity is not None and record.humidity < 35:
        add_evidence("drought", 0.9, 45, "空气湿度偏低")
    elif record.humidity is not None and record.humidity > 90:
        add_evidence("pest", 0.8, 42, "空气湿度过高，病害风险上升")

    is_daytime = 8 <= record.timestamp.hour <= 17
    if is_daytime and record.light is not None and record.light < 180:
        add_evidence("low_light", 2.2, 44, "白天光照强度偏低")

    if record.rainfall is not None and record.rainfall > 8:
        add_evidence("waterlogging", 2.0, 55, "短时降雨量较高")
    if (
        record.rainfall is not None
        and record.soil_moisture is not None
        and record.rainfall > 6
        and record.soil_moisture > 50
    ):
        add_evidence("waterlogging", 3.8, 72, "降雨量较高且土壤湿度偏高")

    if candidates:
        _, dominant_risk, main_reason = max(candidates, key=lambda item: item[0])
        reasons.insert(0, main_reason)
    else:
        evidence["healthy"] += 6.0
        dominant_risk = "healthy"
        reasons.insert(0, "环境传感器指标处于正常范围")

    probabilities = normalize_distribution(evidence)
    score = probability_risk_score(probabilities)
    reliability = 1.0 - 0.18 * len(record.missing_fields) - 0.22 * len(record.anomaly_fields)
    reliability = clamp(reliability, 0.35, 1.0)

    return ModalityAssessment(
        score=score,
        dominant_risk=dominant_risk,
        reliability=reliability,
        probabilities=probabilities,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def assess_vision(record: CleanedRecord) -> ModalityAssessment:
    status_to_reason = {
        "healthy": "图像标签显示作物状态健康",
        "drought": "图像标签疑似干旱",
        "pest": "图像标签疑似病虫害",
        "waterlogging": "图像标签疑似积水",
        "unknown": "图像标签未知",
    }
    confidence = record.vision_confidence
    evidence = {state: 0.08 for state in STATE_LABELS}

    if record.image_status == "healthy":
        evidence["healthy"] += 1.0 + 6.0 * confidence
        for state in ("drought", "heat", "pest", "waterlogging", "low_light"):
            evidence[state] += 0.3 * (1 - confidence)
    elif record.image_status == "unknown":
        evidence["healthy"] += 1.0
        for state in ("drought", "pest", "waterlogging"):
            evidence[state] += 0.8
    else:
        evidence[record.image_status] += 1.0 + 5.5 * confidence
        evidence["healthy"] += 1.5 * (1 - confidence)
        for state in ("drought", "pest", "waterlogging"):
            if state != record.image_status:
                evidence[state] += 0.25

    probabilities = normalize_distribution(evidence)
    score = probability_risk_score(probabilities)
    dominant_risk = dominant_state(probabilities, score)
    reasons = [status_to_reason[record.image_status]]
    if confidence < 0.5:
        reasons.append("视觉置信度不足，不能单独作为强决策依据")

    return ModalityAssessment(
        score=score,
        dominant_risk=dominant_risk,
        reliability=confidence,
        probabilities=probabilities,
        reasons=tuple(reasons),
    )


def compute_dynamic_fusion_weights(
    record: CleanedRecord,
    environment: ModalityAssessment,
    vision: ModalityAssessment,
    conflicts: tuple[str, ...],
) -> FusionWeights:
    sensor_weight = 0.62 * environment.reliability
    vision_weight = 0.38 * vision.reliability
    adjustments: list[str] = []

    if record.missing_fields:
        sensor_weight *= 0.72
        adjustments.append("传感器存在缺失值，降低环境模态权重")
    if record.anomaly_fields:
        sensor_weight *= 0.68
        adjustments.append("传感器存在异常值，降低环境模态权重")
    if record.vision_confidence < 0.5:
        vision_weight *= 0.55
        adjustments.append("视觉置信度低，降低视觉模态权重")
    elif record.vision_confidence < 0.7:
        vision_weight *= 0.78
        adjustments.append("视觉置信度中等，轻微降低视觉模态权重")
    if conflicts:
        sensor_weight *= 0.9
        vision_weight *= 0.65
        adjustments.append("环境和视觉存在冲突，降低直接执行可靠性")

    total_weight = sensor_weight + vision_weight
    if total_weight <= 0:
        return FusionWeights(
            sensor_weight=1.0,
            vision_weight=0.0,
            reliability_adjustments=("所有模态可靠性过低，退化为环境保守估计",),
        )

    return FusionWeights(
        sensor_weight=sensor_weight / total_weight,
        vision_weight=vision_weight / total_weight,
        reliability_adjustments=tuple(dict.fromkeys(adjustments)),
    )


def fuse_probabilities(
    environment: ModalityAssessment,
    vision: ModalityAssessment,
    fusion_weights: FusionWeights,
) -> ProbabilityDistribution:
    sensor_weight = fusion_weights.sensor_weight
    vision_weight = fusion_weights.vision_weight

    fused = {
        state: (
            environment.probabilities[state] * sensor_weight
            + vision.probabilities[state] * vision_weight
        )
        for state in STATE_LABELS
    }
    return normalize_distribution(fused)


def detect_conflicts(
    record: CleanedRecord,
    environment: ModalityAssessment,
    vision: ModalityAssessment,
) -> tuple[str, ...]:
    conflicts: list[str] = []

    if (
        record.image_status == "drought"
        and record.soil_moisture is not None
        and record.soil_moisture >= 35
    ):
        conflicts.append("图像疑似干旱，但土壤湿度处于正常范围")

    if (
        record.image_status == "waterlogging"
        and record.soil_moisture is not None
        and record.rainfall is not None
        and record.soil_moisture <= 35
        and record.rainfall < 2
    ):
        conflicts.append("图像疑似积水，但土壤湿度和降雨量不支持")

    if record.image_status == "healthy" and environment.score >= 50:
        conflicts.append("图像显示健康，但环境传感器提示较高风险")

    if record.image_status in {"drought", "pest", "waterlogging"} and vision.reliability < 0.5:
        conflicts.append("图像标签存在风险，但视觉置信度过低")

    return tuple(conflicts)


def detect_temporal_trends(records: Sequence[CleanedRecord]) -> tuple[str, ...]:
    if len(records) < TREND_WINDOW_SIZE:
        return ()

    flags: list[str] = []
    soil_values = [record.soil_moisture for record in records if record.soil_moisture is not None]
    if len(soil_values) >= TREND_WINDOW_SIZE:
        soil_drop = soil_values[0] - soil_values[-1]
        decreasing_steps = sum(
            1 for previous, current in zip(soil_values, soil_values[1:]) if current < previous
        )
        if soil_drop >= 4 and decreasing_steps >= 4:
            flags.append("soil_moisture_decreasing_6h")

    temperatures = [
        record.temperature
        for record in records
        if record.temperature is not None and "temperature" not in record.anomaly_fields
    ]
    if len(temperatures) >= TREND_WINDOW_SIZE and sum(temperatures) / len(temperatures) >= 34:
        flags.append("sustained_high_temperature_6h")

    wet_observations = [
        record
        for record in records
        if (
            record.rainfall is not None
            and record.soil_moisture is not None
            and (record.rainfall > 2 or record.soil_moisture > 52)
        )
    ]
    if len(wet_observations) >= 4:
        flags.append("persistent_wet_condition_6h")

    return tuple(flags)


def apply_temporal_evidence(
    probabilities: ProbabilityDistribution,
    trend_flags: tuple[str, ...],
) -> ProbabilityDistribution:
    adjusted = dict(probabilities)
    if "soil_moisture_decreasing_6h" in trend_flags:
        adjusted["drought"] += 0.12
    if "sustained_high_temperature_6h" in trend_flags:
        adjusted["heat"] += 0.10
    if "persistent_wet_condition_6h" in trend_flags:
        adjusted["waterlogging"] += 0.10

    return normalize_distribution(adjusted)


def smooth_probabilities(
    current: ProbabilityDistribution,
    previous: ProbabilityDistribution | None,
) -> ProbabilityDistribution:
    if previous is None:
        return current

    smoothed = {
        state: EMA_ALPHA * current[state] + (1 - EMA_ALPHA) * previous[state]
        for state in STATE_LABELS
    }
    return normalize_distribution(smoothed)


def detect_consistency_flags(
    probabilities: ProbabilityDistribution,
    previous_belief: ProbabilityDistribution | None,
    trend_flags: tuple[str, ...],
) -> tuple[str, ...]:
    flags: list[str] = []
    risk_score = probability_risk_score(probabilities)
    current_state = dominant_state(probabilities, risk_score)

    if previous_belief is not None and current_state != "healthy":
        previous_state = dominant_state(
            previous_belief,
            probability_risk_score(previous_belief),
        )
        if (
            previous_state == current_state
            and previous_belief[current_state] >= 0.35
            and probabilities[current_state] >= 0.35
        ):
            flags.append("same_risk_state_consistent_with_previous_belief")

    trend_support = {
        "drought": "soil_moisture_decreasing_6h",
        "heat": "sustained_high_temperature_6h",
        "waterlogging": "persistent_wet_condition_6h",
    }
    if current_state in trend_support and trend_support[current_state] in trend_flags:
        flags.append("temporal_trend_supports_dominant_state")

    return tuple(flags)


def apply_consistency_evidence(
    probabilities: ProbabilityDistribution,
    consistency_flags: tuple[str, ...],
) -> ProbabilityDistribution:
    if not consistency_flags:
        return probabilities

    adjusted = dict(probabilities)
    risk_score = probability_risk_score(adjusted)
    current_state = dominant_state(adjusted, risk_score)
    if current_state == "healthy":
        return probabilities

    if "same_risk_state_consistent_with_previous_belief" in consistency_flags:
        adjusted[current_state] += 0.08
    if "temporal_trend_supports_dominant_state" in consistency_flags:
        adjusted[current_state] += 0.06

    return normalize_distribution(adjusted)


def trend_reasons(trend_flags: tuple[str, ...]) -> tuple[str, ...]:
    reason_map = {
        "soil_moisture_decreasing_6h": "最近 6 小时土壤湿度持续下降，干旱状态概率上升",
        "sustained_high_temperature_6h": "最近 6 小时持续高温，热胁迫状态概率上升",
        "persistent_wet_condition_6h": "最近 6 小时存在持续湿润或降雨，积水状态概率上升",
    }
    return tuple(reason_map[flag] for flag in trend_flags)


def consistency_reasons(consistency_flags: tuple[str, ...]) -> tuple[str, ...]:
    reason_map = {
        "same_risk_state_consistent_with_previous_belief": "当前主风险与上一时刻状态信念一致，系统置信度上升",
        "temporal_trend_supports_dominant_state": "时间趋势支持当前主风险，系统置信度上升",
    }
    return tuple(reason_map[flag] for flag in consistency_flags)


def score_to_level(score: float) -> str:
    if score >= 80:
        return "高"
    if score >= 60:
        return "中高"
    if score >= 40:
        return "中"
    if score >= 20:
        return "低"
    return "很低"


def uncertainty_to_level(score: float) -> str:
    if score >= 70:
        return "高"
    if score >= 30:
        return "中"
    return "低"


def assess_uncertainty(
    record: CleanedRecord,
    conflicts: tuple[str, ...],
    state_confidence: float,
    consistency_flags: tuple[str, ...],
) -> float:
    score = 0.0
    if record.missing_fields:
        score += 32
    if record.anomaly_fields:
        score += 35
    if record.vision_confidence < 0.5:
        score += 28
    if record.image_status == "unknown":
        score += 16
    if conflicts:
        score += 35
    if state_confidence < 0.45:
        score += 12
    if (
        consistency_flags
        and not conflicts
        and not record.missing_fields
        and not record.anomaly_fields
        and record.vision_confidence >= 0.5
    ):
        score -= 10

    return clamp(score, 0, 100)


def decide_safety_action(
    risk_score: float,
    uncertainty_score: float,
) -> SafetyDecision:
    if risk_score >= 60 and uncertainty_score < 30:
        return SafetyDecision(
            action_permission="execute",
            safety_action="execute_recommended_action",
            safety_policy="高风险 + 低不确定性 → 允许执行建议动作",
        )

    if risk_score >= 60 and uncertainty_score >= 30:
        return SafetyDecision(
            action_permission="hold",
            safety_action="recheck_before_action",
            safety_policy="高风险 + 高不确定性 → 先复查，不直接执行动作",
        )

    if risk_score >= 40 and uncertainty_score >= 30:
        return SafetyDecision(
            action_permission="hold",
            safety_action="resample_before_action",
            safety_policy="中风险 + 高不确定性 → 重新采样后再决策",
        )

    if risk_score < 40 and uncertainty_score < 30:
        return SafetyDecision(
            action_permission="observe",
            safety_action="routine_patrol",
            safety_policy="低风险 + 低不确定性 → 常规巡检",
        )

    return SafetyDecision(
        action_permission="hold",
        safety_action="monitor_more_context",
        safety_policy="风险或不确定性处于中间状态 → 继续观察并收集更多上下文",
    )


def build_recommendation(
    record: CleanedRecord,
    dominant_risk: str,
    risk_level: str,
    uncertainty_score: float,
) -> str:
    actions: list[str] = []

    if uncertainty_score >= 30:
        actions.append("优先让机器人复查该区域并重新采样")
    if "soil_moisture" in record.missing_fields:
        actions.append("补采土壤湿度数据")
    if "temperature" in record.anomaly_fields:
        actions.append("复测或校准温度传感器")

    if dominant_risk == "drought":
        actions.append("若低湿状态连续出现，触发灌溉提醒")
    elif dominant_risk == "heat":
        actions.append("增加高温巡检频率并检查遮阴或降温条件")
    elif dominant_risk == "pest":
        actions.append("安排近距离图像复核并标记疑似病虫害区域")
    elif dominant_risk == "waterlogging":
        actions.append("检查排水情况并降低灌溉优先级")
    elif dominant_risk == "low_light":
        actions.append("继续观察光照变化，必要时调整巡检时间")
    elif dominant_risk == "sensor_anomaly":
        actions.append("不要直接执行农业动作，先确认传感器读数")
    elif risk_level in {"很低", "低"} and not actions:
        actions.append("继续常规巡检")

    return "；".join(dict.fromkeys(actions))


def assess_record(
    record: CleanedRecord,
    temporal_window: Sequence[CleanedRecord],
    previous_belief: ProbabilityDistribution | None,
) -> tuple[RiskAssessment, ProbabilityDistribution]:
    environment = assess_environment(record)
    vision = assess_vision(record)
    conflicts = detect_conflicts(record, environment, vision)
    fusion_weights = compute_dynamic_fusion_weights(record, environment, vision, conflicts)
    fused_probabilities = fuse_probabilities(environment, vision, fusion_weights)
    trend_flags = detect_temporal_trends(temporal_window)
    temporally_adjusted = apply_temporal_evidence(fused_probabilities, trend_flags)
    ema_probabilities = smooth_probabilities(temporally_adjusted, previous_belief)
    consistency_flags = detect_consistency_flags(
        probabilities=ema_probabilities,
        previous_belief=previous_belief,
        trend_flags=trend_flags,
    )
    smoothed_probabilities = apply_consistency_evidence(
        probabilities=ema_probabilities,
        consistency_flags=consistency_flags,
    )

    risk_score = probability_risk_score(smoothed_probabilities)
    if conflicts and max(environment.score, vision.score) >= 50:
        risk_score = max(risk_score, 45)

    dominant_risk = dominant_state(smoothed_probabilities, risk_score)
    state_confidence = smoothed_probabilities[dominant_risk]
    uncertainty_score = assess_uncertainty(
        record=record,
        conflicts=conflicts,
        state_confidence=state_confidence,
        consistency_flags=consistency_flags,
    )
    risk_level = score_to_level(risk_score)
    uncertainty_level = uncertainty_to_level(uncertainty_score)
    safety_decision = decide_safety_action(risk_score, uncertainty_score)
    reasons = (
        environment.reasons
        + vision.reasons
        + fusion_weights.reliability_adjustments
        + tuple(f"数据冲突：{conflict}" for conflict in conflicts)
        + trend_reasons(trend_flags)
        + consistency_reasons(consistency_flags)
    )
    recommendation = build_recommendation(
        record=record,
        dominant_risk=dominant_risk,
        risk_level=risk_level,
        uncertainty_score=uncertainty_score,
    )

    assessment = RiskAssessment(
        timestamp=record.timestamp_text,
        risk_score=round(risk_score, 1),
        risk_level=risk_level,
        state_confidence=round(state_confidence, 2),
        uncertainty_score=round(uncertainty_score, 1),
        uncertainty_level=uncertainty_level,
        dominant_risk=dominant_risk,
        sensor_score=round(environment.score, 1),
        vision_score=round(vision.score, 1),
        sensor_reliability=round(environment.reliability, 2),
        vision_reliability=round(vision.reliability, 2),
        dynamic_sensor_weight=round(fusion_weights.sensor_weight, 2),
        dynamic_vision_weight=round(fusion_weights.vision_weight, 2),
        reliability_adjustments=fusion_weights.reliability_adjustments,
        sensor_probabilities=environment.probabilities,
        vision_probabilities=vision.probabilities,
        fused_probabilities=fused_probabilities,
        smoothed_probabilities=smoothed_probabilities,
        trend_flags=trend_flags,
        consistency_flags=consistency_flags,
        conflict_flags=conflicts,
        action_permission=safety_decision.action_permission,
        safety_action=safety_decision.safety_action,
        safety_policy=safety_decision.safety_policy,
        reasons=tuple(dict.fromkeys(reasons)),
        recommendation=recommendation,
        uncertainty_case=record.uncertainty_case,
    )
    return assessment, smoothed_probabilities


def read_input_rows() -> list[dict[str, str]]:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"找不到输入数据文件: {INPUT_PATH}")

    with INPUT_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"输入数据文件为空: {INPUT_PATH}")
        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"输入数据缺少必要字段: {missing}")
        return list(reader)


def write_results(results: list[RiskAssessment]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    probability_columns = [f"p_{state}" for state in STATE_LABELS]
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "timestamp",
                "risk_score",
                "risk_level",
                "state_confidence",
                *probability_columns,
                "uncertainty_score",
                "uncertainty_level",
                "dominant_risk",
                "sensor_score",
                "vision_score",
                "sensor_reliability",
                "vision_reliability",
                "dynamic_sensor_weight",
                "dynamic_vision_weight",
                "reliability_adjustments",
                "sensor_probabilities",
                "vision_probabilities",
                "fused_probabilities",
                "smoothed_probabilities",
                "trend_flags",
                "consistency_flags",
                "conflict_flags",
                "action_permission",
                "safety_action",
                "safety_policy",
                "reasons",
                "recommendation",
                "uncertainty_case",
            ],
        )
        writer.writeheader()
        for result in results:
            probability_values = {
                f"p_{state}": f"{result.smoothed_probabilities[state]:.3f}"
                for state in STATE_LABELS
            }
            writer.writerow(
                {
                    "timestamp": result.timestamp,
                    "risk_score": f"{result.risk_score:.1f}",
                    "risk_level": result.risk_level,
                    "state_confidence": f"{result.state_confidence:.2f}",
                    **probability_values,
                    "uncertainty_score": f"{result.uncertainty_score:.1f}",
                    "uncertainty_level": result.uncertainty_level,
                    "dominant_risk": result.dominant_risk,
                    "sensor_score": f"{result.sensor_score:.1f}",
                    "vision_score": f"{result.vision_score:.1f}",
                    "sensor_reliability": f"{result.sensor_reliability:.2f}",
                    "vision_reliability": f"{result.vision_reliability:.2f}",
                    "dynamic_sensor_weight": f"{result.dynamic_sensor_weight:.2f}",
                    "dynamic_vision_weight": f"{result.dynamic_vision_weight:.2f}",
                    "reliability_adjustments": "；".join(result.reliability_adjustments),
                    "sensor_probabilities": format_probabilities(result.sensor_probabilities),
                    "vision_probabilities": format_probabilities(result.vision_probabilities),
                    "fused_probabilities": format_probabilities(result.fused_probabilities),
                    "smoothed_probabilities": format_probabilities(result.smoothed_probabilities),
                    "trend_flags": "；".join(result.trend_flags),
                    "consistency_flags": "；".join(result.consistency_flags),
                    "conflict_flags": "；".join(result.conflict_flags),
                    "action_permission": result.action_permission,
                    "safety_action": result.safety_action,
                    "safety_policy": result.safety_policy,
                    "reasons": "；".join(result.reasons),
                    "recommendation": result.recommendation,
                    "uncertainty_case": result.uncertainty_case,
                }
            )


def print_examples(results: list[RiskAssessment]) -> None:
    print(f"Generated {len(results)} risk assessments at {OUTPUT_PATH}")
    print()
    print("不确定性测试样例：")
    for result in results:
        if result.uncertainty_case == "normal":
            continue
        print(f"- 时间：{result.timestamp}")
        print(f"  风险等级：{result.risk_level}")
        print(f"  主状态：{result.dominant_risk}，置信度：{result.state_confidence:.2f}")
        print(f"  状态概率：{format_probabilities(result.smoothed_probabilities)}")
        print(
            f"  动态权重：sensor={result.dynamic_sensor_weight:.2f}, "
            f"vision={result.dynamic_vision_weight:.2f}"
        )
        print(f"  不确定性：{result.uncertainty_level} ({result.uncertainty_score:.1f})")
        print(f"  安全策略：{result.safety_policy}")
        print(f"  原因：{'；'.join(result.reasons)}")
        print(f"  建议：{result.recommendation}")


def main() -> None:
    rows = read_input_rows()
    records = sorted((clean_record(row) for row in rows), key=lambda record: record.timestamp)
    results: list[RiskAssessment] = []
    previous_belief: ProbabilityDistribution | None = None

    for index, record in enumerate(records):
        window_start = max(0, index - TREND_WINDOW_SIZE + 1)
        temporal_window = records[window_start : index + 1]
        assessment, previous_belief = assess_record(
            record=record,
            temporal_window=temporal_window,
            previous_belief=previous_belief,
        )
        results.append(assessment)

    write_results(results)
    print_examples(results)


if __name__ == "__main__":
    main()
