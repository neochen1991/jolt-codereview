import { C, addBg, foot, node, panel, text, title } from "./shared.mjs";

export async function slide07(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  title(slide, ctx, "DEMO STORYBOARD", "Demo 不展示“会聊天”，而展示从 MR 到证据化结论的闭环。", 7);
  const beats = [
    ["准备", "选择一个真实 MR", "展示变更范围、风险标签、评审配置"],
    ["启动", "创建 Agent Review", "任务进入队列，显示预算和进度"],
    ["推理", "展开 Trace", "看到工具调用、候选发现、Agent 分工"],
    ["治理", "Verifier / Judge", "展示为何保留、合并或拒绝发现"],
    ["输出", "报告与评论", "从最终 Issue 跳回文件、证据和修复建议"],
  ];
  beats.forEach((b, i) => {
    const x = 70 + i * 232;
    node(slide, ctx, x, 246, 190, 148, b[0], `${b[1]}\n${b[2]}`, { fill: i === 2 ? "#E7F3FF" : "#FFFFFF", stroke: i === 2 ? C.teal : C.line, labelSize: 20, subSize: 12 });
    text(slide, ctx, `0${i + 1}`, x + 10, 214, 42, 20, { size: 18, color: C.amber, bold: true, mono: true });
    if (i < beats.length - 1) ctx.addShape(slide, { left: x + 195, top: 318, width: 28, height: 2, fill: C.line });
  });
  panel(slide, ctx, 150, 492, 980, 74, { fill: "#FFFFFF", stroke: "#B8D5F0" });
  text(slide, ctx, "Demo 关键判据", 176, 516, 132, 18, { size: 14, color: C.teal, bold: true });
  text(slide, ctx, "观众能否回答：这个问题来自哪里？为什么可信？如何修？如果误报，反馈如何回流？", 326, 510, 720, 28, { size: 19, color: C.text });
  foot(slide, ctx, "建议 Demo 使用本仓库 seeded MR 或用户指定 MR；重点展示证据链，而非单次模型输出。");
  return slide;
}
