# 测试

所有测试数据均为程序生成的合成数据（文件名与内容标注 SYNTHETIC），不含论文或真实实验数值。

## 1. 自动化测试清单（2026-10-26）

| 范围 | 数量 | 内容 |
|---|---|---|
| `packages/mechanics` | 107 | 单位换算与量纲拒绝；统计；单轴（线性材料精确解、neo-Hookean 闭式 W(λ)、微分模量、硬化、断裂检测、缺尺寸拒绝、Hypothesis 缩放/可加性）；循环（闭合滞回解析面积、阶梯幅度、软化、残余应变、不闭合、未完成、噪声）；纯剪切（Gc 精确解、候选 λc 为临时值、时间同步、几何告警、禁止外推）；疲劳（稳态判定、检测限 0.4 nm/cycle 例、删失不为 0、阈值回收、拒绝条件、约定混用拒绝、实验区间措辞）；DMA（已知 tan δ 由 E″/E′ 复原、网格间峰位插值、E″ 峰对照密集网格真值、E′ 切线交点精确解、不一致告警、多峰不选定与限定区间、范围外不外推、异常点检出且平滑噪声零误报、多频率分组、频率扫描、参考温度插值、单位缩放不变）。分支覆盖率 93%，门槛 90% |
| `packages/dataio` | 52 | 14 张 fixture 表头识别；GBK/BOM/分号小数逗号/空白分隔/多工作表；千分位不猜测；损坏文件；映射安全性（未标记确认的映射必须正确）；单位换算；质量检查各项；修正记录；元数据要求 |
| `packages/database` | 39 | 迁移幂等、迁移失败报告备份、归档只读去重与篡改检测、Parquet、追加式版本与哈希、事务回滚、单一来源约束、文献提取方式约束；文献导入（SI 换算、原文写法保留、幂等与原地更正、10 类非法记录整份拒绝、实验材料不合并、真实论文数据文件校验与抽查）；可比性规则（12 个场景） |
| `packages/plotting` | 12 | 17 个模板、JSON 往返、单位换算、非法 Spec 拒绝、PNG/SVG/PDF 导出（SVG 文字可编辑） |
| `apps/api` | 28 | 端到端工作流（导入→实验→分析→重新计算→比较→CSV→绘图→报告）、缺尺寸 422、多工作表、循环、纯剪切、疲劳阈值链、DMA（Tg 各定义、性能记录、多频率分组比较、重新计算、报告）、文献导入与列表、可比性接口、多面板导出（SVG 面板标号）与图中数据 CSV、版面容量校验、自定义模板与已保存配置分开、材料库对比散点（同一材料多条记录全部绘出）、数据修正（预览不保存、保存、作用于新版本并改变输入哈希、旧版本不变、停用后历史保留、4 类非法参数 422）、AI 文献对标（不发送本实验名称与数值、候选与规则结论、拒绝材料名不符与带单位数值、Provider 失败回退）、AI 契约（含 28 条真实录制响应的安全性检查）、Mac↔Bridge 协议、Bridge 不可达降级 |
| `tests/` | 5 | 包依赖方向 |
| `bridge/windows-origin/tests` | 19 | Token、请求上限、串行队列、下载白名单与路径穿越、Schema 拒绝（LabTalk 注入、越界列、非法文件名、路径式模板名）、清理范围、模板注册表字段与真实 `.otpu`、模板解析（native / 文件缺失 / 哈希不符 / 未注册 → 回退） |
| 前端 Vitest | 3 | 显示单位与数字格式 |
| Playwright（WebKit + Chromium） | 9 × 2 | 循环拉伸（分割、逐循环表、滞后能曲线）；纯剪切（自动选同材料无裂纹样品、人工确认 λc、Gc 非临时）；疲劳（稳态能量 → 裂纹扩展速率，分辨率取自元数据）；DMA（Tg 按定义列出、tan δ 峰 −15 °C）；数据修正（预览、保存、作用于新版本并记入溯源、停用）；导入→映射→检查→元数据→创建实验；计算→新版本→比较；绘图工作室导出 PNG、添加面板并用键盘添加系列、切换面板模板、导出图中数据、保存自定义模板、报告；设置外观、键盘隐藏侧边栏、Origin 未连接降级；每页 axe WCAG 2 A/AA 扫描（serious/critical 为 0） |

运行：`make check`（全部 Python + 前端类型与 Vitest）、`make e2e`（Playwright，独立端口与临时数据目录）。

## 2. 真实环境验证

| 项目 | 脚本 | 结果与记录 |
|---|---|---|
| Origin 最小链路（Phase 0） | `bridge/windows-origin/phase0_origin_smoke.py` | 通过，`reports/data/origin/phase0/` |
| Bridge VM 内自测 | `bridge/windows-origin/bridge_selftest.py` | 通过，`reports/data/origin/bridge_selftest_20261025/` |
| Origin 模板库生成与回退 | `bridge/windows-origin/make_templates.py`、`bridge_selftest.py` | 通过，`reports/data/origin/templates_20261026/` |
| SPEC §6.7 十步端到端 | `scripts/acceptance_origin_e2e.py` | 通过（含 Mac 收到的 OPJU 在全新 Origin 实例中重开核验），`reports/data/origin/e2e_20261026/`；新模板重跑 `e2e_20261026_run2/` |
| AI 列映射评测（真实调用） | `scripts/eval_ai_mapping.py` | `reports/data/ai_eval/mapping_eval_20261026.json` |
| AI 文献对标评测（真实调用，Codex + Claude 各 4 次） | `scripts/eval_ai_benchmark.py` | `reports/data/ai_eval/benchmark_eval_20261026.json`：8/8 有效输出，0 条引用越界或材料名不符，0 处带单位数值，0 处与规则结论矛盾的“可直接比较” |
| 质量检查注入评测、批量耗时、手算对照 | `scripts/eval_quality_and_batch.py` | `reports/data/eval/quality_batch_20261026.json` |

## 3. 未覆盖 / 未验证

- 真实仪器导出的原始数据（仓库中没有真实数据；全部为合成数据）。
- 界面上的 AI 列识别按钮在 E2E 中未调用真实模型（后端真实调用已单独评测）。
- 疲劳阈值与 AI 按钮的界面流程未做 E2E（API 层已测；AI 后端真实调用另有评测）。
- Origin 输出带 “demo” 水印（授权问题，见 `docs/ORIGIN_BRIDGE.md` §2.2）。
