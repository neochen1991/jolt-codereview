# Frontend TypeScript Standard

## 规范说明
适用于 TS/TSX/React 前端代码检视。

## 检查点
- `useEffect` 依赖必须完整，异步请求要处理取消或过期响应。
- 状态更新不得依赖过期闭包。
- API 数据进入 UI 前必须处理 null/undefined。

## 如何检查
1. 搜索新增 hook、事件和 fetch 调用。
2. 检查状态流是否覆盖失败和竞态。
3. 检查组件是否使用 button/input/label 等语义元素。

## 反例
```tsx
useEffect(() => { fetchData(id); }, []);
```

## 正例
```tsx
useEffect(() => { fetchData(id); }, [id]);
```
