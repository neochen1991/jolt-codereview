# Skill 草稿保存即编译设计

## 目标

Skill 版本创建或整包上传时已经会生成 Checkpoint Manifest，但单独编辑 `SKILL.md` 或 `references/*` 后，草稿中保存的 Manifest 仍可能是旧内容。本次改动让每次版本资源保存都立即使用 `SkillCheckpointCompiler` 重编译，使调试看到的草稿编译结果始终对应当前资源；激活时继续执行相同校验，正式任务仍只读取激活版本中持久化的不可变 Manifest。

## 方案比较

1. **保存即同步编译，激活再复核（采用）**：反馈即时，调试和正式任务共用同一编译器及产物格式；编译失败允许草稿继续保存，但明确标记为无效并禁止激活。
2. **仅前端预编译**：响应快，但浏览器与服务端容易产生版本漂移，不能作为正式任务可信产物。
3. **异步后台编译**：适合超大 Bundle，但当前 Markdown 编译开销很小，会引入队列状态与短暂陈旧窗口。

## 数据流

版本资源保存请求先规范化资源，再由 Repository 在事务中更新 `assets_json`。随后路由对更新后的完整 Bundle 调用现有 `validateSkillBundlePayload`，并将 `validation_json`、`checkpoint_manifest_json`、`checkpoint_compiler_version` 与 Bundle hash 一并写回当前草稿版本。响应返回更新后的版本行，因此调用方可立即读取最新的校验状态和 Manifest。

编译失败不回滚资源内容：草稿必须可逐步编辑；失败详情持久化在 `validation_json`，调试启动和激活门禁根据最新校验状态拒绝使用无效产物。激活仍从当前资源重新编译一次，防止绕过保存链路或旧数据污染。

不带 `version` 的 `/custom-skill-assets` 写入属于兼容的激活资源镜像，不允许借此修改激活版本的 Manifest；版本化草稿编辑必须显式提交 `version`。

## 界面与错误处理

资源保存成功后，界面显示“已保存并重新编译”，并使用响应中的 `validation_json` 更新当前校验结果。若当前 Bundle 尚不完整，仍提示资源已保存，同时列出具体编译/校验错误。活动版本继续保持不可变。

## 测试

- Repository/路由契约测试验证版本资源写入后会调用完整 Bundle 校验并持久化最新 Manifest。
- 验证有效资源编辑会改变 checkpoint 内容和 Bundle hash。
- 验证无效编辑会被保存、`validation_json.ok=false`，并继续被激活门禁拦截。
- 运行后端构建、Skill 定向验证和仓库完整 `npm run verify`。
