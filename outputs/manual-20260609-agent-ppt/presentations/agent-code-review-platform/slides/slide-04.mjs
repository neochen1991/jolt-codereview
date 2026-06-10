import { C, addBg, foot, node, panel, text, title } from "./shared.mjs";

export async function slide04(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  title(slide, ctx, "ARCHITECTURE", "架构的关键不是堆模型，而是把入口、编排、工具、证据和发布边界拆开。", 4);
  const layers = [
    ["体验层", "React Review Console", "MR / Full Review / Trace / Feedback"],
    ["平台 API", "TypeScript API + RBAC 边界", "项目、MR、任务、报告、集成配置"],
    ["任务与状态", "Queue + Job Repository", "去重、重试、状态机、审计日志"],
    ["Agent 编排", "Python LangGraph Worker", "Planner / Specialists / Debate / Judge / Verifier"],
    ["工具与上下文", "Static Tools + Repo Context", "Diff、规则、依赖、历史问题、代码索引"],
    ["发布与沉淀", "GitHub / CodeHub Provider", "Summary、评论、反馈学习、质量报表"],
  ];
  layers.forEach((l, i) => {
    const y = 210 + i * 66;
    panel(slide, ctx, 86, y, 1010, 48, { fill: i === 3 ? "#E7F3FF" : "#FFFFFF", stroke: i === 3 ? C.teal : C.line, strokeWidth: i === 3 ? 2 : 1 });
    text(slide, ctx, l[0], 108, y + 15, 100, 16, { size: 12, color: C.amber, bold: true });
    text(slide, ctx, l[1], 240, y + 10, 300, 20, { size: 17, color: C.text, bold: true });
    text(slide, ctx, l[2], 580, y + 13, 470, 17, { size: 12, color: C.muted });
  });
  node(slide, ctx, 1124, 236, 96, 88, "Evidence", "trace\nartifacts\nbudget", { fill: "#E7F3FF", stroke: C.blue, labelSize: 15 });
  node(slide, ctx, 1124, 352, 96, 88, "Quality", "verifier\njudge\ngold eval", { fill: "#EAF8F0", stroke: C.green2, labelSize: 15 });
  node(slide, ctx, 1124, 468, 96, 88, "Risk", "auth\nqueue\npublish", { fill: "#FFF0F0", stroke: C.red, labelSize: 15 });
  foot(slide, ctx, "仓库语境：React + TS API + Python/LangGraph worker + Verifier/Judge + static tools + GitHub/CodeHub provider。");
  return slide;
}
