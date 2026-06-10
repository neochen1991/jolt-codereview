import { C, addBg, foot, panel, text } from "./shared.mjs";

export async function slide09(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  text(slide, ctx, "DECISION", 56, 42, 220, 22, { size: 12, color: C.teal, bold: true });
  text(slide, ctx, "建议以 MR Review 场景启动试点，先证明评审闭环，再扩大平台边界。", 56, 150, 760, 118, { size: 42, color: C.text, bold: true });
  const checks = [
    ["选 2-3 个高变更频率项目", "覆盖 Java/TypeScript 等典型代码栈"],
    ["建立金标与反馈机制", "把误报、漏报、采纳率纳入周度复盘"],
    ["锁定生产硬化清单", "认证/RBAC、队列可靠性、发布权限、审计日志"],
    ["定义上线门槛", "只有通过治理门的发现进入最终报告和评论"],
  ];
  checks.forEach((c, i) => {
    const y = 326 + i * 70;
    ctx.addShape(slide, { left: 84, top: y + 8, width: 18, height: 18, fill: i < 2 ? C.teal : C.amber });
    text(slide, ctx, c[0], 124, y, 330, 24, { size: 20, color: C.text, bold: true });
    text(slide, ctx, c[1], 480, y + 5, 520, 18, { size: 13, color: C.muted });
  });
  panel(slide, ctx, 904, 122, 260, 136, { fill: "#E7F3FF", stroke: C.teal, strokeWidth: 2 });
  text(slide, ctx, "下一步", 930, 150, 120, 20, { size: 15, color: C.teal, bold: true });
  text(slide, ctx, "用一个真实 MR\n跑完整 Demo\n沉淀试点评分表", 930, 184, 198, 54, { size: 18, color: C.text });
  foot(slide, ctx, "Deck date: 2026-06-09. 内容为汇报稿，不替代实时生产审计。");
  return slide;
}
