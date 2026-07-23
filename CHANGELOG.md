# 更新日志

## [v1.4.3] - 2026-07-23
### 修复
- 修复 `@llm_tool` 装饰器调用时传递 `event` 参数的问题
- 函数签名需要包含 `event` 参数来接收框架传递的事件对象

## [v1.4.2] - 2026-07-23
### 修复
- 修复 `@llm_tool` 装饰器调用时参数重复传递的问题
- 使用 `**kwargs` 接收参数，避免 "got multiple values for argument" 错误

## [v1.4.1] - 2026-07-23
### 修复
- 修复 `@llm_tool` 装饰器在实例方法上导致的 "got multiple values for argument" 运行时错误
- 将 `btp_llm_tool` 和 `bt_search_llm_tool` 改为静态方法，避免 self 重复绑定

## [v1.4.0] - 2026-07-23
### 新增
- 新增 `bt_search` 和 `bt_preview` 两个 LLM 函数调用工具（`@llm_tool`），AstrBot 大模型可自动调用
- LLM 可通过 `bt_search` 搜索磁力链接并从中提取链接
- LLM 可通过 `bt_preview` 查询磁链预览信息

## [v1.3.0] - 2026-05-14
### 新增
- 搜索结果自动附带 whatslink.info 预览（类型、文件数、预览图）
- 新增 `btp` 独立预览命令，可单独查询磁链详情
- 新增 `enable_preview` 配置项，可开关搜索结果的预览功能

### 优化
- 开启预览时隐藏搜索自带的文件大小，避免与 whatslink 数据重复
