import { C, addBg, foot, lane, panel, text, title } from "./shared.mjs";

export async function slide02(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  title(slide, ctx, "SCENARIO MAP", "Agent 的高价值场景，不在“回答问题”，而在驱动带工具的工程动作。", 2);
  const cols = ["需求澄清", "设计评审", "代码开发", "MR 评审", "上线治理"];
  cols.forEach((c, i) => {
    const x = 82 + i * 226;
    panel(slide, ctx, x, 238, 188, 276, { fill: i === 3 ? "#E7F3FF" : "#FFFFFF", stroke: i === 3 ? C.teal : C.line, strokeWidth: i === 3 ? 2 : 1 });
    text(slide, ctx, c, x + 18, 256, 150, 24, { size: 18, bold: true, color: i === 3 ? C.teal : C.text });
    const lines = [
      ["用户故事拆解", "验收标准补全", "风险问题追问"],
      ["方案对齐", "依赖扫描", "安全/性能预审"],
      ["代码生成", "测试补齐", "局部重构建议"],
      ["Diff 理解", "多 Agent 审阅", "证据化结论输出"],
      ["发布门禁", "缺陷复盘", "质量知识沉淀"],
    ][i];
    lines.forEach((l, j) => text(slide, ctx, l, x + 20, 306 + j * 42, 144, 20, { size: 13, color: C.muted }));
  });
  text(slide, ctx, "三种成熟度", 72, 560, 130, 18, { size: 13, color: C.amber, bold: true });
  lane(slide, ctx, 210, 548, 918, "从低到高：", ["Copilot 式建议", "Tool-use 自动化", "Workflow Agent + 治理闭环"], C.amber);
  foot(slide, ctx, "框架：按 SDLC 场景归纳；Jolt 当前最适合作为 MR 评审与质量治理场景切入。");
  return slide;
}
