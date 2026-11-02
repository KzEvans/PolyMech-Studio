# Origin 模板库验证（2026-10-26，真实 OriginPro 2025b 10.250212）

- `make_templates_report.json`：`bridge/windows-origin/make_templates.py` 的输出。4 个模板全部保存成功；从 `.otpu` 重新加载后逐项读回样式属性（showAxes=3、showLabels=1、ticks=5，双 Y 右轴层 ticks=5），与设置值一致。
- `pm_*_check.png`：由保存的 `.otpu` 新建图页并加入合成数据后导出的检查图。
- `bridge_selftest_result.json`：Bridge 自测（合成单轴数据）：GStress、GDouble 走注册的 `.otpu`（`template_mode: native`），GFallback 使用未注册 id，回退到内置模板 + 程序化样式（`programmatic`，附中文警告）；重新打开 OPJU 核验通过，自建 Origin 实例全部退出。
- 图片中的 “demo” 水印为已知授权问题（见 `docs/ORIGIN_BRIDGE.md` §2.2），按用户指示暂时忽略。
- 同日 §6.7 十步验收以新模板重跑：`../e2e_20261026_run2/`（`pm_line`，native）。
