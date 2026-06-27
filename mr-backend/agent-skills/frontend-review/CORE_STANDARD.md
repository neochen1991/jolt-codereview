# Frontend Core Standard

## 规范说明
只报告前端状态、交互、异步、可访问性、浏览器安全和用户路径问题。

## 检查点
- loading/error/empty/success 状态是否完整。
- 表单提交是否防重复、校验、可恢复。
- 交互控件是否可键盘访问且有语义。

## 如何检查
1. 定位组件状态和事件处理。
2. 检查异步失败路径与用户反馈。
3. 检查按钮、输入、列表和弹窗的可访问性。

## 反例
```tsx
<div onClick={submit}>提交</div>
```

## 正例
```tsx
<button type="button" onClick={submit}>提交</button>
```
