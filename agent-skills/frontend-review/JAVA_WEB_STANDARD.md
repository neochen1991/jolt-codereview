# Frontend Agent Java Web 代码规范

适用专家：Frontend Agent

适用范围：Java Web 配套前端中的 React / Vue / TypeScript 页面、表单、状态、接口调用、可访问性、浏览器安全和用户体验。

排除范围：服务端安全、后端事务、DDD、数据库专项、Redis 和 Java 性能问题。

## 输出要求

每个前端 finding 必须说明用户可见影响、触发路径和建议修改代码。

## FE-ASYNC-001 异步请求必须处理 loading/error/empty 状态

### 规范说明

页面请求必须处理加载中、失败、空数据和重试，避免用户误以为数据正常。

### 检查点

- 是否只有成功态渲染。
- 请求失败是否有提示。
- 空列表是否和加载中混淆。
- 是否支持刷新或重试。

### 如何检查

1. 查找 `fetch`、`axios`、query hook。
2. 检查状态变量和渲染分支。
3. 判断用户是否能恢复失败。

### 反例

```tsx
return <Table rows={data.items} />;
```

### 正例

```tsx
if (loading) return <Spinner />;
if (error) return <ErrorState onRetry={reload} />;
if (!data.items.length) return <EmptyState />;
return <Table rows={data.items} />;
```

## FE-FORM-002 表单必须有校验、禁用态和失败恢复

### 规范说明

表单提交必须处理字段校验、重复提交、服务端错误和提交后状态。

### 检查点

- submit 时按钮是否 disabled。
- 是否处理服务端错误。
- 是否显示字段级错误。
- 是否防止重复点击。

### 如何检查

1. 查找 form submit。
2. 检查 pending 状态。
3. 检查错误渲染。

### 反例

```tsx
<button onClick={submit}>保存</button>
```

### 正例

```tsx
<button disabled={submitting || !formValid} onClick={submit}>
  保存
</button>
{error && <FormError message={error.message} />}
```

## FE-HOOK-003 Hook 依赖和闭包必须正确

### 规范说明

React hook 必须避免 stale state、遗漏依赖和重复请求。

### 检查点

- `useEffect` 依赖数组是否遗漏变量。
- 回调是否读取旧状态。
- 是否在 unmount 后 setState。

### 如何检查

1. ESLint hooks 规则候选。
2. 检查 effect 内引用变量。
3. 检查异步取消逻辑。

### 反例

```tsx
useEffect(() => {
  load(projectId);
}, []);
```

### 正例

```tsx
useEffect(() => {
  let cancelled = false;
  load(projectId).then((value) => {
    if (!cancelled) setData(value);
  });
  return () => { cancelled = true; };
}, [projectId]);
```

## FE-A11Y-004 交互控件必须可访问

### 规范说明

按钮、弹窗、菜单、表单控件必须具备可访问名称、键盘可操作性和焦点管理。

### 检查点

- icon button 是否有 aria-label。
- 弹窗是否 `role=dialog` 和 `aria-modal`。
- clickable div 是否可键盘触发。
- 表单控件是否有 label。

### 如何检查

1. 检查 JSX 交互元素。
2. 使用 eslint jsx-a11y 候选。
3. 判断键盘路径是否可达。

### 反例

```tsx
<div onClick={openDetail}>详情</div>
```

### 正例

```tsx
<button type="button" onClick={openDetail} aria-label="查看问题详情">
  <InfoIcon />
</button>
```

## FE-XSS-005 不得直接渲染未净化 HTML

### 规范说明

用户输入、后端返回、Markdown、日志内容不得未经净化直接渲染为 HTML。

### 检查点

- `dangerouslySetInnerHTML`
- `v-html`
- URL 是否校验协议。
- Markdown 是否经过 sanitizer。

### 如何检查

1. 查找危险渲染 API。
2. 判断内容来源。
3. 检查 DOMPurify 或可信白名单。

### 反例

```tsx
<div dangerouslySetInnerHTML={{ __html: comment }} />
```

### 正例

```tsx
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(comment) }} />
```

## FE-LAYOUT-006 关键内容不得溢出、重叠或不可见

### 规范说明

企业工作台页面必须保证表格、弹窗、按钮、代码块在桌面视口下稳定布局。

### 检查点

- 长路径、长标题是否省略或换行。
- 弹窗内容是否可滚动。
- 主按钮是否在底部可见。
- 代码块是否使用等宽格式和横向滚动。

### 如何检查

1. 用浏览器检查 1440x900 和 1920x1080。
2. 检查 scrollWidth 是否超过 clientWidth。
3. 检查弹窗底部操作是否可见。

### 反例

```tsx
<pre>{code}</pre>
```

无边界和滚动控制。

### 正例

```tsx
<pre className="code-block">
  <code>{code}</code>
</pre>
```
