import { C, addBg, foot, metric, panel, text, title } from "./shared.mjs";

export async function slide06(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  title(slide, ctx, "VALUE MODEL", "落地价值应该用工程指标说话：更快评审、更少逃逸、更强可追踪。", 6);
  const pillars = [
    ["Reviewer Focus", "把低价值扫描和重复说明交给 Agent，人类聚焦架构、业务语义和高风险决策。", C.teal],
    ["Defect Discovery", "多 Agent 专家视角覆盖安全、可靠性、业务逻辑和测试缺口。", C.amber],
    ["Governance", "Trace、预算、Verifier、Judge 让评审过程可复盘、可审计、可改进。", C.blue],
    ["Platform Learning", "反馈与金标评测形成质量闭环，沉淀团队自己的 Review 标准。", C.green2],
  ];
  pillars.forEach((p, i) => {
    const x = 62 + (i % 2) * 570;
    const y = 222 + Math.floor(i / 2) * 136;
    panel(slide, ctx, x, y, 520, 104, { fill: "#FFFFFF", stroke: p[2] });
    text(slide, ctx, p[0], x + 24, y + 20, 210, 24, { size: 21, bold: true, color: p[2] });
    text(slide, ctx, p[1], x + 24, y + 55, 460, 30, { size: 13, color: C.muted });
  });
  metric(slide, ctx, 106, 548, "TTR", "Time to Review", C.teal, 160);
  metric(slide, ctx, 306, 548, "Escape", "线上缺陷逃逸", C.red, 160);
  metric(slide, ctx, 506, 548, "FP Rate", "误报与噪音", C.amber, 160);
  metric(slide, ctx, 706, 548, "Trace", "审计可追踪率", C.blue, 160);
  metric(slide, ctx, 906, 548, "Adopt", "团队采纳率", C.green2, 160);
  foot(slide, ctx, "未使用虚构 ROI；建议试点期以上述 KPI 建基线、跑 2-4 周对比。");
  return slide;
}
