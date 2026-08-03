# Agricultural_monitoring_system_based_on_IoT_data

## 具体场景

本项目定位为一个面向农业/野外巡检机器人的作物状态监测与风险判断系统。机器人在农田或温室环境中巡检时，持续采集环境传感器数据，并结合模拟图像状态识别结果，判断作物是否存在干旱、高温、低光照、积水或异常风险，最终输出风险等级和行动建议。

当前阶段先不依赖真实硬件、真实传感器或真实图像，而是使用模拟环境数据完成系统原型。这样可以先验证数据处理、风险判断和后续多模态融合流程，等有真实设备或公开数据集后再替换数据输入层。

## 目标描述

系统根据温度、空气湿度、土壤湿度、光照、降雨量、图像状态标签和图像置信度，判断作物生长风险，并给出可解释的建议动作。例如：当土壤湿度持续偏低且图像标签显示干旱时，系统应识别为干旱风险；当图像标签置信度较低或传感器数据冲突时，系统应降低决策确定性，并建议机器人复查该区域。

## 模拟环境数据

已生成 1000 条模拟环境数据：

- 数据文件：`data/mock_environment_data.csv`
- 生成脚本：`scripts/generate_mock_environment_data.py`
- 时间范围：从 `2026-08-03 00:00` 开始，按小时生成

字段说明：

| 字段 | 含义 | 单位 |
| --- | --- | --- |
| `timestamp` | 数据采集时间 | 年-月-日 时:分 |
| `temperature` | 环境温度 | 摄氏度 |
| `humidity` | 空气湿度 | % |
| `soil_moisture` | 土壤湿度 | % |
| `light` | 光照强度 | 归一化强度 0-1000 |
| `rainfall` | 小时降雨量 | mm |
| `image_status` | 模拟图像识别结果，包含 `healthy`、`drought`、`pest`、`waterlogging`、`unknown` | 类别 |
| `vision_confidence` | 图像识别置信度 | 0-1 |
| `uncertainty_case` | 不确定性测试类型，正常数据为 `normal` | 类别 |

## 模拟图像标签

当前项目不直接使用真实图片，而是用 `image_status` 和 `vision_confidence` 表示图像识别模块的输出：

```csv
image_status,vision_confidence
healthy,0.92
drought,0.81
pest,0.74
unknown,0.35
```

这样可以先研究“视觉结果存在不确定性时，系统如何融合传感器数据并做出稳健决策”。后续如果加入真实图像模型，只需要把模型预测结果写入这两个字段即可。

## 不确定性测试

数据集中已人为插入 4 类测试场景：

| `uncertainty_case` | 含义 | 目的 |
| --- | --- | --- |
| `sensor_missing_soil_moisture` | 土壤湿度字段为空 | 测试传感器缺失时系统是否能继续判断 |
| `data_conflict_vision_drought_soil_normal` | 图像显示干旱，但土壤湿度正常 | 测试多模态数据冲突处理 |
| `low_vision_confidence` | 图像置信度固定为 0.35 | 测试低置信度视觉结果对决策的影响 |
| `noisy_temperature_spike` | 温度被设置为异常高值 | 测试传感器噪声或异常值检测 |

## 核心算法流程

核心算法已实现为 `scripts/analyze_crop_risk.py`，完整流程如下：

```text
模拟数据输入
→ 数据清洗
→ 单模态概率状态估计
→ 动态模态可靠性调整
→ 多模态概率融合
→ 时间序列状态平滑
→ 不确定性评估
→ 安全决策层
→ 输出风险等级和建议动作
```

### 1. 模拟数据输入

算法读取 `data/mock_environment_data.csv`，输入字段包括环境传感器数据、模拟图像标签、图像置信度和不确定性测试标签。

### 2. 数据清洗

数据清洗阶段负责：

- 检查必要字段是否存在
- 将温度、湿度、土壤湿度、光照、降雨量、视觉置信度转换为数值
- 识别缺失值，例如土壤湿度为空
- 识别异常值，例如温度超过合理范围
- 校验 `image_status` 是否属于允许类别

### 3. 单模态概率状态估计

算法不再只输出“是否干旱”这样的硬判断，而是把环境状态建模为概率分布：

```text
P(healthy)=0.18
P(drought)=0.62
P(heat)=0.08
P(pest)=0.03
P(waterlogging)=0.04
P(low_light)=0.02
P(sensor_anomaly)=0.03
```

环境传感器单独估计一次状态概率，输出 `sensor_probabilities` 和 `sensor_score`。例如：

- 土壤湿度低：干旱风险
- 温度高：热胁迫风险
- 降雨量高且土壤湿度高：积水风险
- 温度异常尖峰：传感器噪声风险

图像标签也单独估计一次状态概率，输出 `vision_probabilities` 和 `vision_score`。例如：

- `drought`：图像疑似干旱
- `pest`：图像疑似病虫害
- `waterlogging`：图像疑似积水
- `unknown` 或低置信度：降低视觉可靠性

### 4. 动态模态可靠性调整

为了让融合过程更接近真实机器人系统，算法会根据数据质量动态调整环境传感器和视觉模态的权重：

| 情况 | 处理方式 |
| --- | --- |
| 传感器缺失 | 降低环境模态权重 |
| 传感器异常 | 降低环境模态权重，并提高不确定性 |
| 视觉置信度低 | 降低视觉模态权重 |
| 模态冲突 | 同时降低直接执行可靠性，提高不确定性 |
| 连续状态一致 | 提高主状态置信度，降低非异常情况下的不确定性 |

输出结果中会记录：

- `dynamic_sensor_weight`
- `dynamic_vision_weight`
- `reliability_adjustments`
- `consistency_flags`

### 5. 多模态概率融合

融合阶段不是直接平均风险等级，而是将传感器概率分布和图像概率分布按可靠性加权：

```text
P_fused(state)
= P_sensor(state) × dynamic_sensor_weight
+ P_vision(state) × dynamic_vision_weight
```

如果出现数据冲突，例如“图像显示干旱，但土壤湿度正常”，算法不会直接相信其中一个模态，而是提高不确定性，并建议机器人复查。

### 6. 时间序列状态平滑

机器人不应该只根据单个时刻做判断，因此算法加入了两个时间序列机制：

- 6 小时滑动窗口：检测土壤湿度持续下降、持续高温、持续湿润等趋势
- 指数移动平均 EMA：将当前融合概率和上一时刻的状态信念进行平滑

平滑公式：

```text
belief_t = α × P_fused_t + (1 - α) × belief_{t-1}
```

当前实现中 `α = 0.42`。这相当于一个简化的 Bayesian filter / HMM 思想：当前观测会更新状态信念，但不会完全覆盖历史趋势。

### 7. 不确定性评估

算法会计算 `uncertainty_score`，主要来源包括：

- 关键传感器缺失
- 传感器异常值
- 图像置信度低
- 图像结果未知
- 图像和环境数据冲突
- 状态概率分布过于分散，即最高状态置信度较低

不确定性越高，系统越倾向于输出“复查、重新采样、人工确认”类建议，而不是直接执行灌溉或排水等动作。

### 8. 安全决策层

系统会根据风险等级和不确定性等级决定是否允许直接执行动作：

| 条件 | 安全策略 |
| --- | --- |
| 高风险 + 低不确定性 | 允许执行建议动作 |
| 高风险 + 高不确定性 | 先复查，不直接执行动作 |
| 中风险 + 高不确定性 | 重新采样后再决策 |
| 低风险 + 低不确定性 | 常规巡检 |
| 其他情况 | 继续观察并收集更多上下文 |

输出结果中会记录：

- `action_permission`
- `safety_action`
- `safety_policy`

### 9. 输出风险等级和建议动作

运行后会生成 `data/risk_assessment_results.csv`，核心字段包括：

| 字段 | 含义 |
| --- | --- |
| `risk_score` | 基于平滑后状态概率计算的风险分数 |
| `risk_level` | 风险等级：很低、低、中、中高、高 |
| `state_confidence` | 当前主风险状态的概率 |
| `p_healthy` 等概率列 | 平滑后的各状态概率 |
| `uncertainty_score` | 不确定性分数 |
| `uncertainty_level` | 不确定性等级：低、中、高 |
| `dominant_risk` | 主要风险类型 |
| `dynamic_sensor_weight` | 动态调整后的环境模态权重 |
| `dynamic_vision_weight` | 动态调整后的视觉模态权重 |
| `reliability_adjustments` | 模态可靠性调整原因 |
| `sensor_probabilities` | 传感器单模态状态概率 |
| `vision_probabilities` | 图像单模态状态概率 |
| `fused_probabilities` | 当前时刻多模态融合概率 |
| `smoothed_probabilities` | 时间平滑后的状态概率 |
| `trend_flags` | 6 小时滑动窗口检测到的趋势 |
| `consistency_flags` | 连续一致性标记 |
| `action_permission` | 是否允许执行动作 |
| `safety_action` | 安全决策动作 |
| `safety_policy` | 安全策略解释 |
| `reasons` | 可解释原因 |
| `recommendation` | 建议动作 |

示例输出逻辑：

```text
风险等级：中高
状态概率：P(healthy)=0.12；P(drought)=0.71；P(heat)=0.06；P(pest)=0.03；P(waterlogging)=0.04；P(low_light)=0.02；P(sensor_anomaly)=0.02
不确定性：中
原因：土壤湿度偏低；图像标签疑似干旱；最近 6 小时土壤湿度持续下降
建议：优先让机器人复查该区域并重新采样；若低湿状态连续出现，触发灌溉提醒
```

## 实验评估指标

已新增 `scripts/evaluate_fusion_methods.py`，用于比较 3 种融合方法：

| 方法 | 含义 |
| --- | --- |
| `rule_fusion` | 规则融合基线 |
| `fixed_weighted_fusion` | 固定权重概率融合 |
| `uncertainty_weighted_fusion` | 动态可靠性 + 时间平滑 + 安全决策融合 |

评估脚本会生成：

- `data/fusion_method_comparison.csv`：整体指标对比
- `data/fusion_method_predictions.csv`：每条样本的预测结果

当前评估指标包括：

| 指标 | 含义 |
| --- | --- |
| `risk_class_accuracy` | 风险类别识别准确率 |
| `binary_risk_accuracy` | 是否存在风险的二分类准确率 |
| `uncertainty_detection_rate` | 不确定性场景检测率 |
| `conflict_detection_rate` | 模态冲突检测率 |
| `anomaly_detection_rate` | 异常值检测率 |
| `safe_hold_rate_on_uncertain_risk` | 不确定中高风险场景下是否能阻止直接执行动作 |

运行评估：

```bash
python3 scripts/evaluate_fusion_methods.py
```

运行风险评估：

```bash
python3 scripts/analyze_crop_risk.py
```

完整运行顺序：

```bash
python3 scripts/generate_mock_environment_data.py
python3 scripts/analyze_crop_risk.py
python3 scripts/evaluate_fusion_methods.py
```
