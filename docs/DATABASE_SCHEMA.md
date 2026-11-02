# 数据库结构

SQLite（SQLAlchemy 2 + Alembic，迁移位于 `packages/database/src/polymech_database/migrations`）。所有物理量以 SI 存储，单位列写明。时间以 UTC 存储，读出为带时区的 UTC 时间。

| 表 | 作用 | 关键字段 / 约束 |
|---|---|---|
| `material` | 材料（实验或文献） | `name` 唯一；`polymer_type`、`structure_type`、`phase_structure`、`block_count`、`origin`（experiment/literature）、`tags` |
| `material_component` | 组成 / 嵌段（SPEC：MaterialComposition、PolymerBlock） | `role`（glassy/rubbery/filler/crosslinker）、`block_label`、`position`、`molar_mass_kg_mol`、`fraction` + `fraction_basis` |
| `sample_batch` | 批次 | (`material_id`, `label`) 唯一 |
| `specimen` | 样品与几何 | `thickness_m`、`width_m`、`gauge_length_m`、`height_m`（纯剪切 H0）、`notch_length_m`；缺失为 NULL，从不默认 |
| `experiment_protocol` | 可复用测试条件 | `conditions` JSON |
| `experiment` | 一次测试 | `test_type`、仪器、日期、`temperature_k`、`stretch_rate_per_s`、`cycle_frequency_hz`、`precycles`、`extra`（如裂纹分辨率） |
| `raw_data_file` | 只读原始文件 | `sha256`、`archive_path`（`raw/ab/<sha256>.<ext>`）、`sheet`、编码、分隔符、说明行字段；同一内容只存一份 |
| `data_column_mapping` | 确认后的列映射 | (`raw_file_id`, `column_index`) 唯一；`quantity`、`unit`、`source`（rules / ai:* / rules+ai:* / profile:* / user）、`confidence` |
| `import_profile` | 仪器导入规则 | `name` 唯一；`rules` JSON |
| `data_correction` | 用户选择的修正 | 原始文件、列、算法、参数（输入与计算结果）、操作者、时间、`active`（停用后保留为历史，迁移 `c3d4e5f6a7b8`）；原始文件始终不变 |
| `analysis_run` | **不可变**的分析版本 | (`experiment_id`, `method`, `version`) 唯一；`params`、`inputs`（含几何与原始文件哈希）、`result`、`flags`、`status`（ok/provisional）、`input_sha256`、`result_sha256`、`curves_path`、`software_version`、`parent_run_id` |
| `mechanical_property` | 性能数值 | `quantity`、`value`（可空：只有区间时）、`unit`（SI）、`uncertainty` + `uncertainty_kind`、`lower_bound`/`upper_bound`、`conditions`；**CHECK：恰好一个来源**（`analysis_run_id` 或 `literature_measurement_id`） |
| `literature_source` | 文献 | 题名、作者、年份、DOI、类型 |
| `literature_measurement` | 文献数值的出处 | 页码、图号、表号；**CHECK：`extraction_method` ∈ {reported, digitized}** |
| `reference_citation` | 材料–文献关联 | — |
| `plot_configuration` | 保存的 PlotSpec | 模板 id 与版本、`spec` JSON |
| `origin_job` | Origin 任务 | Bridge 任务号、状态、OPJU/PNG 路径、核验结果 |

性能词表（`PROPERTY_UNITS`）：elastic_modulus、tensile_strength、break_stress、ultimate_stretch、work_of_fracture、fracture_toughness、fatigue_threshold、hysteresis_energy、residual_strain、storage_modulus、loss_modulus、loss_factor、glass_transition_temperature、interfacial_toughness。新增指标只需扩展词表，不改表结构。

版本规则：同一实验、同一方法的每次计算都新增一行（`version + 1`），旧行不修改；`compare_runs` 给出参数与结果差异。临时结果（如 λc 未确认、未达稳态、阈值不可辨识）不写入性能表中的确定数值。
