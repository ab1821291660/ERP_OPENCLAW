





#### 4.8.6 典型故障复盘一：旧请求覆盖新请求

**现象**：用户连续发送 A、B，两次模型调用并发，A 最后返回并写入状态，覆盖 B 的新意图。

**根因**：只在 HTTP 层异步执行，没有身份级权威请求、提交前 active 校验和请求级状态隔离。

**治理**：identityKey 串行器 + active request claim + latest-wins + 中断 + commit 前多次 `ensureActive` + canceled rollback。

**剩余边界**：分布式场景必须确认共享 KV 的租约实现已启用；单机锁不能代替多实例一致性。

#### 4.8.7 典型故障复盘二：岗位话术与 active_job 不一致

**现象**：用户看到岗位 B，但后续答疑或拉群使用岗位 A。

**根因**：模型展示岗位与状态切换是两个独立步骤，候选结果也可能串轮。

**治理**：本轮工具结果按 requestId 归属；`set_active_job` 同时接收岗位 ID 和完整话术；先权威校验并暂存状态，成功后才 returnDirect；提交失败不发送成功话术。

#### 4.8.8 典型故障复盘三：建群成功但文员未入群

**现象**：群已创建、候选人已在群，但指定文员缺席；如果只看 createRoom 成功，会误判交付完成。

**根因**：把 API 请求成功当成成员事实，缺少文员成员查询、确认时间窗和替换状态。

**治理**：以 membership 查询为事实源；区分 JOINED、ABSENT、UNKNOWN；按 2/5/10 分钟推进确认，失败换人、安抚和告警；租约与 milestone 防止重复执行。

#### 4.8.9 典型故障复盘四：促活误打扰

**现象**：任务生成后用户已经回复或删除好友，系统仍发送促活。

**根因**：只在任务生成时检查，缺少发送前的实时事实校验。

**治理**：claim 后再次检查用户活动、实时私聊回复、好友关系、发送时间窗和岗位状态；分别返回 cancel、retry later、fail 或 allow。

#### 4.8.10 典型故障复盘五：子任务完成但没有回答用户

**现象**：AUTO 委派的子任务或工具已经完成，主回复却只汇报“执行成功”，没有回答用户原始问题；或者汇总阶段再次调用写工具，造成重复副作用。

**根因**：把 task completion 当成 conversation completion，未区分工具回执、证据、未决项和用户可见答案；汇总角色仍带有执行工具权限。

**治理**：子任务保存结构化 receipt 和状态；主流程根据 DIRECT/DELEGATE/PAUSE/SUMMARY 明确收口；只读汇总上下文不携带执行域与写工具；最终发布仍回到原 owner，且同一副作用不能因汇总失败被重跑。




#### 4.8.13 代码证据索引
以下路径均为仓库相对路径，面试前可直接复制定位：

| 主题 | 证据路径 | 可核验内容 |
| --- | --- | --- |
| 构建与技术栈 | `pom.xml` | Java 21、Spring Boot、Spring AI Alibaba、Dubbo、RocketMQ、Nacos 等版本和模块聚合 |
| 项目定位 | `docs/文档总览.md` | 业务范围、核心架构口径和设计原则 |
| 总体设计 | `docs/主对话/C端智能体整体技术设计方案.md` | 分层、模块、业务流程和稳定性设计 |
| HTTP 入口 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/web/WecomController.java` | chat、event、回调模拟、Session/Memory 调试接口 |
| 句子 MQ 入口 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/messaging/juzibot/JuzibotSentenceCallbackConsumerHandler.java` | MQ 消费、回调适配与主链调用 |
| 消息合并 | `cwecome-craw-conversation/cwecome-craw-conversation-inbound/src/main/java/com/aihire/cwecraw/appali/messaging/coalesce/WecomTurnCoalescer.java` | 短窗口合并、active run 替换与 drain |
| 入站处理 | `cwecome-craw-conversation/cwecome-craw-conversation-inbound/src/main/java/com/aihire/cwecraw/appali/messaging/consumer/WecomInboundProcessor.java` | turn buffer、主对话调用、出站与 checkpoint |
| 主对话编排 | `cwecome-craw-conversation/cwecome-craw-conversation-wecom/src/main/java/com/aihire/cwecraw/wecom/WecomChatService.java` | requestId、行业路由、Agent 调用、guard、commit/rollback、事件 |
| 本地轮次串行 | `cwecome-craw-conversation/cwecome-craw-conversation-wecom/src/main/java/com/aihire/cwecraw/wecom/SessionTurnSequencer.java` | identityKey 进程内串行；不等同分布式锁 |
| 并发协调 | `cwecome-craw-conversation/cwecome-craw-conversation-wecom/src/main/java/com/aihire/cwecraw/wecom/SessionExecutionCoordinator.java` | latest-wins、取消、关键阶段保护、状态标记 |
| Session 存储 | `cwecome-craw-conversation/cwecome-craw-conversation-wecom/src/main/java/com/aihire/cwecraw/session/KvSessionStore.java` | claim、active 列、锁、租约、旧快照保护 |
| Memory 存储 | `cwecome-craw-conversation/cwecome-craw-conversation-wecom/src/main/java/com/aihire/cwecraw/agent/evolution/KvMemoryStore.java` | 请求级记忆暂存、提交、回滚、身份迁移 |
| Agent 处理器 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/AliAgentWecomChatProcessor.java` | AgentRequest、runtime context、Tool/Skill 结果归属、direct reply 解码 |
| 长对话压缩 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/memory/AihireCompressingConversationMemoryService.java` | 摘要、工具配对修复、候选响应瘦身、推理元数据清理 |
| 通用规则 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/resources/workspace/aihire-wecom-agent/AGENTS.md` | 事实优先级、真实动作、隐私和输出边界 |
| Skill 选择 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/IndustrySkillSelector.java` | 模型可见通用 Skill 与行业 Policy 隔离 |
| Policy 装配 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/skill/RuntimePolicyContextAssembler.java` | 通用规则、唯一行业 Policy 与运行时快照 |
| Nacos Skill | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/skill/NacosIndustrySkillConfigClient.java` | 远程配置、缓存、校验和回退 |
| 岗位工具 | `cwecome-craw-conversation/cwecome-craw-conversation-tools/cwecome-craw-tool-job/src/main/java/com/aihire/cwecraw/tools/job/AihireJobServiceTool.java` | `job_tools` 动作与 `set_active_job` |
| direct reply 纠错 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/activejob/ActiveJobReturnDirectRecoveryHook.java` | 校验失败回到模型而非直接暴露 |
| 拉群工具 | `cwecome-craw-conversation/cwecome-craw-conversation-tools/cwecome-craw-tool-group/src/main/java/com/aihire/cwecraw/tools/group/AihireGroupDeliveryTool.java` | readiness、资格校验、建群及后续动作 |
| 好友关系 | `cwecome-craw-candidate/src/main/java/com/aihire/cwecraw/candidate/wecomrelation/ops/WecomFriendRelationOperationsImpl.java` | eventId 幂等、好友接受、关系绑定与失败记录 |
| 好友派发 | `cwecome-craw-candidate/src/main/java/com/aihire/cwecraw/candidate/wecomrelation/dispatch/WecomFriendDispatchOperationsImpl.java` | 任务 claim 与 success/reschedule/failed/canceled |
| 好友重试 | `cwecome-craw-candidate/src/main/java/com/aihire/cwecraw/candidate/wecomrelation/retry/WecomRelationRetryOperationsImpl.java` | 分类型重试、换账号与重试耗尽 |
| 标签任务 | `cwecome-craw-candidate/src/main/java/com/aihire/cwecraw/candidate/tag/service/TagExtractTaskServiceImpl.java` | 短窗口防重、任务与批次创建 |
| 标签执行 | `cwecome-craw-candidate/src/main/java/com/aihire/cwecraw/candidate/tag/service/TagExtractionWorkerServiceImpl.java` | 原子 claim、分批、校验、快照与 partial success |
| 促活发送 | `cwecome-craw-cron/cwecome-craw-cron-reactivation/src/main/java/com/aihire/cwecraw/reactivation/service/ReactivationDispatchService.java` | claim、黑窗、guard、发送、历史和岗位回写 |
| 发送前保护 | `cwecome-craw-cron/cwecome-craw-cron-reactivation/src/main/java/com/aihire/cwecraw/reactivation/service/ReactivationPreSendGuard.java` | 用户回复、好友删除、失败策略 |
| 外呼客户端 | `cwecome-craw-outbound/cwecome-craw-outbound-aliyun/src/main/java/com/aihire/cwecraw/outboundbot/AliyunOutboundBotClient.java` | 通道提交、路由、A/B 分组、响应解析与脱敏日志 |
| 文员补偿 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/groupcompensation/DefaultStaffJoinCompensationService.java` | 成员查询、换人、2/5/10 分钟确认、安抚和告警 |
| 补偿状态 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/groupcompensation/StaffJoinCompensationPhase.java` | 补偿阶段与终态 |
| 业务事件 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/analytics/SlsConversationEventEmitter.java` | 统一字段、异步 SLS 发送及失败隔离 |
| 模型观测 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/AihireModelObservabilityInterceptor.java` | 模型请求、行业 Policy、消息与工具数量 |
| Langfuse | `cwecome-craw-conversation/cwecome-craw-observability-langfuse/src/main/java/com/aihire/cwecraw/langfuse/observability/langfuse/CweLangfuseEventFactory.java` | trace、generation、tool span 与脱敏 |
| OTel 观测 | `cwecome-craw-conversation/cwecome-craw-observability-langfuse/src/main/java/com/aihire/cwecraw/langfuse/observability/langfuse/CweOtelRecorder.java` | OpenTelemetry operation 生命周期、模型与工具观测 |
| Langfuse 协议 | `cwecome-craw-conversation/cwecome-craw-observability-langfuse/src/main/java/com/aihire/cwecraw/langfuse/observability/langfuse/LangfuseConfiguration.java` | Legacy/OTel 主出口与镜像装配、Noop 和故障隔离 |
| 指标枚举 | `cwecome-craw-common/cwecome-craw-monitor/src/main/java/com/aihire/cwecraw/monitor/CwecomeMetric.java` | 会话、Tool、LLM、KV 和身份迁移指标 |
| 实验准入 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/ConversationHistoryExperimentEligibilityResolver.java` | 新旧会话判定与历史欢迎语边界 |
| 实验事件 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/analytics/ExperimentEnrichingConversationEventEmitter.java` | 实验上下文写入业务事件 |
| conversation 模块 | `cwecome-craw-conversation/pom.xml` | core、wecom、inbound、group、agent、tools、观测和 Harness 聚合 |
| Harness 模式 | `cwecome-craw-conversation/cwecome-craw-conversation-agent-ali/src/main/java/com/aihire/cwecraw/agentali/AihireHarnessProperties.java` | REACT/AUTO/CHECKLIST、部署配置与预算参数 |
| Harness 执行器 | `cwecome-craw-conversation/cwecome-craw-conversation-harness/src/main/java/com/aihire/cwecraw/harness/HarnessConversationExecution.java` | owner 边界、准入、工具分级、预算、AUTO/PLAN 执行 |
| AUTO 旧链委派 | `cwecome-craw-conversation/cwecome-craw-conversation-harness/src/main/java/com/aihire/cwecraw/harness/CWecomLegacyAutoExecution.java` | 原 REACT 上的按需委派、回执、未决项与一次性收尾 |
| 群业务结构 | `docs/group-agent/module-layout.md` | 私聊/群聊分域、依赖方向、交接和群消息执行链 |
| 群 Agent 装配 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/group/GroupAgentAutoConfiguration.java` | 摘要、群 Agent、仓储、租约、派发和历史投影装配 |
| 群交接摘要 | `docs/group-agent/handoff-summary.md` | 职位/求职对象范围、引用校验、降级和持久化边界 |
| TableStore 历史 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/java/com/aihire/cwecraw/appali/memory/TableStoreConversationMessageStore.java` | 分块、TTL、metadata 提交点、读失败与中断语义 |
| 配置安全审计 | `cwecome-craw-app/cwecome-craw-app-ali/src/main/resources/application-conversation.yml` | 仅用于确认应做 Secret 注入与凭据轮换；不得复制默认凭据内容 |

