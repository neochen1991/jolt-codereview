const C = {
  bg: "#F6FAFF",
  bg2: "#EAF4FF",
  panel: "#FFFFFF",
  panel2: "#EEF6FF",
  text: "#12324A",
  muted: "#496A83",
  dim: "#7D96AB",
  line: "#C9DDF0",
  teal: "#1378D1",
  amber: "#F5A623",
  red: "#D94B4B",
  blue: "#1C8DFF",
  green2: "#2FA36B",
};

const font = "PingFang SC";
const mono = "Menlo";

export function addBg(slide, ctx) {
  ctx.addShape(slide, { left: 0, top: 0, width: ctx.W, height: ctx.H, fill: C.bg });
  ctx.addShape(slide, { left: 0, top: 0, width: ctx.W, height: 720, fill: "#F6FAFF" });
  ctx.addShape(slide, { left: 0, top: 0, width: ctx.W, height: 92, fill: "#FFFFFF" });
  ctx.addShape(slide, { left: 0, top: 92, width: 1280, height: 1, fill: C.line });
}

export function text(slide, ctx, str, x, y, w, h, opts = {}) {
  return ctx.addText(slide, {
    text: str,
    left: x,
    top: y,
    width: w,
    height: h,
    fontSize: opts.size ?? 22,
    color: opts.color ?? C.text,
    bold: opts.bold ?? false,
    typeface: opts.mono ? mono : font,
    align: opts.align ?? "left",
    valign: opts.valign ?? "top",
    fill: opts.fill ?? "#00000000",
    line: { fill: opts.line ?? "#00000000", width: opts.lineWidth ?? 0 },
    insets: opts.insets ?? { left: 0, right: 0, top: 0, bottom: 0 },
    name: opts.name,
  });
}

export function title(slide, ctx, kicker, claim, page) {
  text(slide, ctx, kicker, 64, 33, 260, 22, {
    size: 12,
    color: C.teal,
    bold: true,
    valign: "mid",
    name: `kicker-${page}-label`,
  });
  ctx.addShape(slide, { left: 46, top: 39, width: 8, height: 8, fill: C.teal, name: `kicker-${page}-marker` });
  text(slide, ctx, claim, 46, 112, 820, 88, { size: 34, bold: true, color: C.text });
  text(slide, ctx, String(page).padStart(2, "0"), 1180, 34, 48, 20, { size: 13, color: C.dim, align: "right" });
}

export function foot(slide, ctx, note) {
  text(slide, ctx, note, 46, 684, 940, 16, { size: 9, color: C.dim });
}

export function panel(slide, ctx, x, y, w, h, opts = {}) {
  return ctx.addShape(slide, {
    left: x,
    top: y,
    width: w,
    height: h,
    fill: opts.fill ?? C.panel,
    line: { fill: opts.stroke ?? C.line, width: opts.strokeWidth ?? 1 },
    name: opts.name,
  });
}

export function rule(slide, ctx, x, y, w, color = C.line) {
  ctx.addShape(slide, { left: x, top: y, width: w, height: 1, fill: color });
}

export function metric(slide, ctx, x, y, value, label, color = C.teal, w = 172) {
  panel(slide, ctx, x, y, w, 74, { fill: "#FFFFFF", stroke: "#B8D5F0" });
  text(slide, ctx, value, x + 14, y + 12, w - 28, 30, { size: 25, bold: true, color });
  text(slide, ctx, label, x + 14, y + 44, w - 28, 16, { size: 10, color: C.muted });
}

export function chip(slide, ctx, str, x, y, w, color = C.teal) {
  panel(slide, ctx, x, y, w, 28, { fill: "#F0F7FF", stroke: color });
  text(slide, ctx, str, x + 10, y + 6, w - 20, 13, { size: 11, color, bold: true, align: "center" });
}

export function node(slide, ctx, x, y, w, h, label, sub, opts = {}) {
  panel(slide, ctx, x, y, w, h, { fill: opts.fill ?? C.panel2, stroke: opts.stroke ?? C.line, strokeWidth: opts.strokeWidth ?? 1.2 });
  text(slide, ctx, label, x + 14, y + 12, w - 28, 24, { size: opts.labelSize ?? 17, bold: true, color: opts.color ?? C.text });
  if (sub) text(slide, ctx, sub, x + 14, y + 42, w - 28, h - 50, { size: opts.subSize ?? 11, color: C.muted });
}

export function lane(slide, ctx, x, y, w, label, items, accent = C.teal) {
  text(slide, ctx, label, x, y, 160, 22, { size: 14, bold: true, color: accent });
  rule(slide, ctx, x, y + 30, w, "#BFD6EA");
  items.forEach((item, i) => {
    const px = x + i * ((w - 20) / items.length);
    ctx.addShape(slide, { left: px, top: y + 46, width: 8, height: 8, fill: accent });
    text(slide, ctx, item, px + 16, y + 39, (w - 20) / items.length - 18, 36, { size: 12, color: C.muted });
  });
}

export { C };
