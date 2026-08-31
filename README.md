# Uncertainty-Aware Multimodal Crop Monitoring

A simulation-based prototype for crop-risk monitoring under uncertain environmental and visual observations. The project demonstrates how sensor readings and mock vision outputs can be fused into probabilistic crop-state estimates, then converted into risk-aware recommendations that defer action when evidence is unreliable or contradictory.

This repository uses **synthetic environmental data** and **mock vision labels** only. It is not an IoT deployment, does not include field data or real imagery, and has not been validated on agricultural hardware or in field conditions.

## Method

The pipeline models the crop state as a probability distribution over healthy, drought, heat, pest, waterlogging, low-light, and sensor-anomaly conditions.

1. Generate deterministic hourly synthetic data for environmental variables and mock visual observations.
2. Validate values, identify missing or anomalous sensor readings, and estimate sensor- and vision-specific state probabilities.
3. Adjust modality weights for missing values, anomalies, low visual confidence, and cross-modal conflicts.
4. Fuse and temporally smooth the state probabilities with a six-hour trend window and exponential moving average.
5. Calculate uncertainty and return a conservative recommendation such as observing, resampling, or rechecking before an intervention.

The evaluation compares a rule baseline, fixed-weight probabilistic fusion, and uncertainty-weighted fusion. Its labels are derived from the synthetic-data rules, so the reported metrics demonstrate internal behavior rather than real-world predictive performance.

## Quick start

The project uses only the Python standard library. From the repository root:

```bash
python3 scripts/generate_mock_environment_data.py
python3 scripts/analyze_crop_risk.py
python3 scripts/evaluate_fusion_methods.py
python3 scripts/visualize_results.py
```

These deterministic commands regenerate the tracked CSV outputs and SVG figures.

## Outputs

| Path | Description |
| --- | --- |
| `data/mock_environment_data.csv` | 1,000 deterministic hourly synthetic observations |
| `data/risk_assessment_results.csv` | Fused state probabilities, uncertainty, safety policy, and recommendation per observation |
| `data/fusion_method_comparison.csv` | Aggregate comparison of the three fusion methods |
| `data/fusion_method_predictions.csv` | Per-observation predictions for each method |
| `figures/*.svg` | Risk, uncertainty, state-probability, and method-comparison visualizations |

On the included synthetic scenario, uncertainty-weighted fusion detects the introduced uncertainty, conflict, and anomaly cases and holds direct action for uncertain medium/high-risk cases. These figures are illustrative results from the simulation, not field-performance claims.

## Repository layout

```text
.
├── data/       # Synthetic input and reproducible evaluation outputs
├── figures/    # SVG visualizations generated from the outputs
├── scripts/    # Standard-library Python pipeline
└── README.md
```

## Limitations

- The environmental values, visual labels, and evaluation labels are simulated.
- `image_status` and `vision_confidence` stand in for a vision model; no model training or images are included.
- Fusion weights, thresholds, and safety policies are hand-designed rather than calibrated from field data.
- Temporal smoothing is a lightweight heuristic, not a validated Bayesian state estimator.
- Recommendations are software outputs only; the project does not control irrigation, robots, or other physical systems.

## Future extensions

Useful next steps include replacing mock inputs with documented public or field datasets, calibrating uncertainty and thresholds against expert labels, evaluating with learned visual models, and connecting the decision layer to a separately validated operational workflow.
