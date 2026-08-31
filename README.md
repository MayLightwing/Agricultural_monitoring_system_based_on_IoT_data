# Uncertainty-Aware Multimodal Crop Monitoring

This research software prototype studies crop-risk decision support when environmental sensing and visual observations are incomplete, uncertain, or inconsistent. It is a simulation-only implementation: inputs are deterministic synthetic sensor records and mock vision labels, and outputs are risk estimates and conservative action recommendations. The repository contains no real IoT stream, field imagery, robot controller, or field-validation result.

## Research question

In a field-robotics monitoring workflow, how should sensor reliability, disagreement between sensing modalities, and temporal context change the decision to execute an intervention, recheck an observation, resample, or continue monitoring rather than force a single classification?

## Method

```text
synthetic hourly input
  -> sensor and mock-vision estimators
  -> reliability-weighted probability fusion
  -> temporal trend analysis and EMA smoothing
  -> risk and uncertainty assessment
  -> safety action: execute, recheck, resample, or monitor
```

The implementation models probabilities for healthy, drought, heat, pest, waterlogging, low-light, and sensor-anomaly states. Missing values, out-of-range readings, low vision confidence, and sensor/vision conflicts reduce modality reliability. A six-hour trend window and exponential moving average provide temporal context before a safety policy selects an action.

## Reproduce

The project uses only the Python standard library.

```bash
python3 scripts/generate_mock_environment_data.py
python3 scripts/analyze_crop_risk.py
python3 scripts/evaluate_fusion_methods.py
python3 scripts/visualize_results.py
```

The commands regenerate the tracked CSV outputs and SVG figures.

```text
.
├── scripts/  # Data generation, risk analysis, evaluation, and SVG rendering
├── data/     # Synthetic inputs and reproducible CSV outputs
└── figures/  # Generated SVG evidence
```

## Evidence

[`data/mock_environment_data.csv`](data/mock_environment_data.csv) contains 1,000 hourly synthetic observations from `2023-12-01 00:00` to `2024-01-11 15:00`; these timestamps locate the simulation within the project period and are not evidence of real collection or deployment. Evaluation produces 3,000 method predictions. The values below are reproduced from [`data/fusion_method_comparison.csv`](data/fusion_method_comparison.csv). Agreement metrics use simulation-derived reference labels and are not field-performance estimates.

| Method | Risk-class agreement | Binary-risk agreement | Uncertainty | Conflict | Anomaly | Safe hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Rule fusion | 0.977 | 0.980 | 0.000 | 0.000 | 1.000 | 0.076 |
| Fixed-weight fusion | 0.966 | 0.968 | 1.000 | 1.000 | 1.000 | 1.000 |
| Uncertainty-weighted fusion | 0.935 | 0.947 | 1.000 | 1.000 | 1.000 | 1.000 |

![Risk score over time](figures/risk_curve.svg)

*Risk score across the synthetic sequence, with decision thresholds and introduced uncertainty cases.*

![State probabilities over time](figures/state_probability_curves.svg)

*Smoothed probabilities for the modeled crop and sensor states.*

![Uncertainty score over time](figures/uncertainty_curve.svg)

*Uncertainty score across the synthetic sequence, with the introduced uncertainty cases marked.*

![Fusion-method comparison](figures/fusion_method_comparison.svg)

*Comparison of the three implemented methods on the simulation-derived evaluation metrics.*

## Limitations and next steps

- The visual labels, sensor readings, reference labels, thresholds, and action policy are simulated; they are not calibrated with field observations.
- The temporal model is a lightweight trend heuristic plus exponential smoothing, not a validated state estimator.
- The action output is decision support only and does not control an agricultural or mobile robot.

Next work should evaluate the policy with documented sensor and perception data, propagate perception and localization confidence into target selection, and test safety margins and re-observation policies on a field-robot platform.
