import { C, addBg, foot, node, panel, text, title } from "./shared.mjs";

export async function slide05(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  title(slide, ctx, "IMPLEMENTATION PRINCIPLE", "一次有效评审，是“候选发现”经过上下文、争辩、验证和投影后的结果。", 5);
  const steps = [
    ["01", "Diff & Scope", "读取 MR diff、变更文件、历史上下文"],
    ["02", "Context Build", "检索代码结构、规则、依赖与相关证据"],
    ["03", "Specialists", "安全、可靠性、业务逻辑、测试覆盖等 Agent 分工"],
    ["04", "Debate", "合并同类项，压低误报，补齐复现证据"],
    ["05", "Verifier / Judge", "门禁判断：是否可行动、是否足够确定"],
    ["06", "Report", "生成报告、发布评论、沉淀反馈"],
  ];
  steps.forEach((s, i) => {
    const x = 52 + i * 198;
    node(slide, ctx, x, 254, 168, 128, s[1], s[2], { fill: i === 4 ? "#FFF6E4" : "#FFFFFF", stroke: i === 4 ? C.amber : C.line });
    text(slide, ctx, s[0], x + 14, 222, 44, 22, { size: 20, color: i === 4 ? C.amber : C.teal, bold: true, mono: true });
    if (i < steps.length - 1) {
      ctx.addShape(slide, { left: x + 172, top: 316, width: 22, height: 2, fill: C.line });
      ctx.addShape(slide, { left: x + 190, top: 312, width: 8, height: 10, fill: C.line });
    }
  });
  panel(slide, ctx, 118, 470, 1042, 80, { fill: "#FFFFFF", stroke: "#B8D5F0" });
  text(slide, ctx, "实现原则", 146, 494, 94, 18, { size: 13, color: C.teal, bold: true });
  text(slide, ctx, "把 SAST / 规则 / Agent 推理都视为候选证据；只有能定位文件、解释风险、给出修复路径并通过治理门的发现，才进入最终报告。", 244, 488, 850, 34, { size: 17, color: C.text });
  foot(slide, ctx, "本页避免把 Agent 简化成模型调用；核心是候选发现到最终 Issue 的治理链路。");
  return slide;
}
