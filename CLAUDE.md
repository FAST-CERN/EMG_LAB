<!-- crg-onboard:v1 开始 -->
## MCP Tools: code-review-graph

**本项目有知识图谱。先用 code-review-graph MCP 工具收窄范围,再读源码。** 图比扫文件便宜,且给出文件搜索给不了的结构信息(调用方、依赖方、测试覆盖)。

### 先用图工具的场景

- **探索代码**:`semantic_search_nodes_tool` 或 `query_graph_tool` 代替 Grep
- **评估影响**:`get_impact_radius_tool` 代替手工追 import
- **代码评审**:`detect_changes_tool` + `get_review_context_tool` 代替通读全文件
- **查关系**:`query_graph_tool` 的 callers_of / callees_of / imports_of / tests_for
- **架构问题**:`get_architecture_overview_tool` + `list_communities_tool`

### 以源码为准

- 用图收窄范围,然后读源码;改动从不只依据图输出。
- 非平凡改动前,读实现与相关测试。
- 触及行为、数据库、迁移、重试、回退、兼容代码时,核对确切源码。
- 图与源码冲突时,源码赢——图可能过期或未建模该关系。
- 图结果为空可能是"未索引"或"静态不可见",不等于"不存在"。

### 工具速查

| 工具 | 场景 |
| ------ | ---------- |
| `detect_changes_tool` | 评审变更——风险评分分析 |
| `get_review_context_tool` | 评审要源码切片——省 token |
| `get_impact_radius_tool` | 变更波及面 |
| `get_affected_flows_tool` | 受影响的执行路径 |
| `query_graph_tool` | 追调用方/被调/导入/测试 |
| `semantic_search_nodes_tool` | 按名字/关键词找函数类 |
| `get_architecture_overview_tool` | 高层结构 |

图随文件变更自动更新(hooks)。会话开场先 `get_minimal_context_tool(task="<任务>")` 拿摘要与建议工具。
<!-- crg-onboard:v1 结束 -->
