import { C, addBg, foot, panel, text, title } from "./shared.mjs";

export async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  addBg(slide, ctx);
  title(slide, ctx, "COMPETITOR VIEW", "竞品集中在助手与单点审查，企业级机会在治理、证据和闭环。", 3);
  const x0 = 54, y0 = 218;
  const widths = [190, 240, 250, 250, 190];
  const headers = ["产品/类别", "核心定位", "优势", "约束", "Jolt 机会"];
  let x = x0;
  headers.forEach((h, i) => {
    panel(slide, ctx, x, y0, widths[i], 38, { fill: "#E7F3FF", stroke: C.line });
    text(slide, ctx, h, x + 12, y0 + 11, widths[i] - 24, 14, { size: 12, color: C.teal, bold: true });
    x += widths[i];
  });
  const rows = [
    ["GitHub Copilot Review", "PR 级辅助审查", "贴近 GitHub 工作流", "治理深度和企业定制有限", "接入多代码平台"],
    ["Cursor / IDE Agent", "开发态辅助", "上下文近、交互快", "偏个人效率，难沉淀组织质量", "连接团队评审资产"],
    ["Devin 类 Coding Agent", "端到端任务执行", "自动化强、叙事吸引", "成本/可控性/验证压力高", "聚焦可验证审阅"],
    ["Qodo / CodeRabbit", "AI Code Review", "评审体验成熟", "差异化依赖规则和治理链", "做证据链与审计"],
    ["Jolt Agent", "工程评审工作流", "多 Agent + Verifier + Trace", "需继续硬化生产边界", "内部试点到平台化"],
  ];
  rows.forEach((r, ri) => {
    const y = y0 + 38 + ri * 62;
    x = x0;
    r.forEach((cell, ci) => {
      const isJolt = ri === rows.length - 1;
      panel(slide, ctx, x, y, widths[ci], 62, { fill: isJolt ? "#DFF0FF" : "#FFFFFF", stroke: isJolt ? C.teal : "#C9DDF0", strokeWidth: isJolt ? 1.5 : 1 });
      text(slide, ctx, cell, x + 12, y + 13, widths[ci] - 24, 32, { size: ci === 0 ? 12 : 11, color: isJolt ? C.text : C.muted, bold: ci === 0 || isJolt });
      x += widths[ci];
    });
  });
  panel(slide, ctx, 854, 576, 350, 62, { fill: "#FFF6E4", stroke: C.amber });
  text(slide, ctx, "定位建议", 876, 592, 88, 16, { size: 12, color: C.amber, bold: true });
  text(slide, ctx, "避开“通用 Copilot”红海，主打可验证评审链路、企业治理与多平台接入。", 966, 588, 210, 26, { size: 12, color: C.text });
  foot(slide, ctx, "注：竞品为公开产品类别视角；本页不使用未授权 logo 或私有指标。");
  return slide;
}
