import { C, addBg, foot, panel, text, title } from "./shared.mjs";

export async function slide08(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  title(slide, ctx, "ROADMAP", "演进重点从“能跑”转向“可信、可控、可规模化”。", 8);
  const phases = [
    ["Phase 1", "受控试点", "MR 主链路稳定演示\n试点 KPI 基线\n反馈闭环与金标样本", C.teal],
    ["Phase 2", "生产硬化", "认证/RBAC 收紧\n队列可靠性与重试\n安全默认值治理", C.amber],
    ["Phase 3", "平台扩展", "Full-review 同级治理\n真实 code index/RAG\n行级评论与多平台发布", C.blue],
  ];
  phases.forEach((p, i) => {
    const x = 94 + i * 370;
    panel(slide, ctx, x, 246, 310, 210, { fill: "#FFFFFF", stroke: p[3], strokeWidth: 2 });
    text(slide, ctx, p[0], x + 24, 270, 90, 18, { size: 13, color: p[3], bold: true, mono: true });
    text(slide, ctx, p[1], x + 24, 304, 180, 28, { size: 28, color: C.text, bold: true });
    text(slide, ctx, p[2], x + 24, 356, 250, 76, { size: 15, color: C.muted });
    if (i < phases.length - 1) ctx.addShape(slide, { left: x + 318, top: 350, width: 44, height: 2, fill: C.line });
  });
  panel(slide, ctx, 130, 530, 1020, 52, { fill: "#FFF0F0", stroke: C.red });
  text(slide, ctx, "当前判断", 156, 548, 100, 16, { size: 13, color: C.red, bold: true });
  text(slide, ctx, "更适合内网受控试点；进入生产全量前应优先完成认证、RBAC、队列与 full-review 治理硬化。", 270, 541, 780, 26, { size: 16, color: C.text });
  foot(slide, ctx, "路线图基于本地审计记忆：主链路完整，但生产边界仍需收紧。");
  return slide;
}
