import { C, metric, panel, text } from "./shared.mjs";

export async function slide01(presentation, ctx) {
  const slide = presentation.slides.add();
  await ctx.addImage(slide, {
    path: `${ctx.assetDir}/agent-command-center.png`,
    left: 700,
    top: 0,
    width: 580,
    height: 720,
    fit: "cover",
    alt: "AI agent command center visual",
  });
  ctx.addShape(slide, { left: 0, top: 0, width: 700, height: 720, fill: "#F6FAFFF4" });
  ctx.addShape(slide, { left: 606, top: 0, width: 110, height: 720, fill: "#F6FAFFD6" });
  text(slide, ctx, "JOLT CODEREVIEW / AGENTIC WORKFLOW", 54, 42, 520, 22, { size: 12, color: C.teal, bold: true });
  text(slide, ctx, "Agent 场景应用、架构原理与落地规划", 54, 150, 640, 132, { size: 48, color: C.text, bold: true });
  text(slide, ctx, "从“AI 写建议”升级到“有证据、有治理、有闭环”的工程评审 Agent。", 58, 306, 560, 64, { size: 23, color: C.muted });
  metric(slide, ctx, 58, 488, "Evidence", "证据优先，而不是纯聊天", C.teal);
  metric(slide, ctx, 246, 488, "Verifier", "多 Agent 结论过验证门", C.amber);
  metric(slide, ctx, 434, 488, "Trace", "过程、预算、产物可追踪", C.blue);
  panel(slide, ctx, 58, 612, 468, 44, { fill: "#FFFFFF", stroke: "#B8D5F0" });
  text(slide, ctx, "适用场景：研发平台汇报 / 试点立项 / 技术方案评审 / Demo 演示", 76, 626, 430, 16, { size: 12, color: C.muted });
  return slide;
}
