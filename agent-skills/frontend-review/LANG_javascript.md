# Frontend JavaScript Standard

## 规范说明
适用于 JavaScript 前端代码检视。

## 检查点
- Promise 必须处理 reject。
- DOM 写入不得使用未净化 HTML。
- 事件处理必须防重复提交。

## 如何检查
1. 搜索 `innerHTML`、`then`、`catch`、事件处理。
2. 检查错误和 loading 状态。
3. 检查用户输入进入 DOM 的路径。

## 反例
```js
container.innerHTML = userInput;
```

## 正例
```js
container.textContent = userInput;
```
