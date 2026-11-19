






#### 4.7.8 典型追问
**问：标签抽取为什么允许 partial_success？**

答：标签按批次执行，单批失败不应抹掉其他可靠结果。保留明细与批次状态后，可以合并有效标签，同时让失败批次进入补偿或人工诊断。

**问：文员邀请失败为什么要区分 UNKNOWN 和 ABSENT？**

答：ABSENT 是权威查询确认未入群，可以换人；UNKNOWN 可能是查询接口异常，直接换人会导致多个文员同时进入群。因此 UNKNOWN 应重试查询。

**问：促活为什么发送前还要查一次？**

答：任务从生成到发送存在时间差，用户可能已经回复、删除好友或岗位下线。生成时检查只能证明过去，发送前 guard 才能阻止过期动作。

**问：状态机如何防止卡死？**

答：每个非终态必须明确 nextAttemptAt、超时和最大重试；processing 状态需要超时回收；同时记录最后失败码和推进版本。没有这些字段的状态机只是枚举，不是可恢复执行器。

**问：为什么群聊要单独建模，不能复用私聊 Session？**

答：私聊 owner 是单个求职者，群聊同时包含求职者、文员、机器人和接管状态；回复时机、权限和停发条件不同。直接复用会让私聊历史、行业 Prompt 和群状态互相污染。共享的是经过校验的业务事实与交接摘要，不是整段运行时上下文。

**问：交接摘要为什么不能只让大模型自由总结？**

答：自由总结无法证明某句话属于哪个职位和求职对象，也无法区分候选岗位、成功切换和失败工具调用。当前方案先用代码做范围筛选、调用结果配对和引用白名单，再让模型抽取结构化 concerns/answered/unresolved，最后仍由代码校验对象、职位、长度和引用。

### 4.8｜稳定性、可观测性、测试与故障复盘

#### 4.8.1 稳定性分层

| 层次 | 当前机制 | 解决的问题 |
| --- | --- | --- |
| 输入层 | 参数校验、消息类型准入、回环过滤 | 非法请求和机器人自循环 |
| 并发层 | identity 串行、latest-wins、关键阶段保护 | 旧回复覆盖新意图、半完成副作用 |
| 模型层 | fallback、超时分类、回复 guard | 模型异常和内部文本泄漏 |
| Tool 层 | 权威校验、错误码、retryable、nextStep | 模型误调用与伪成功 |
| 状态层 | request stage/commit/rollback、revision、lease | 脏写、旧快照覆盖与多实例竞争 |
| 异步层 | claim、幂等、重试、终态、补偿 | 重复消息和临时依赖失败 |
| 出站层 | 发送前 guard、状态回写、历史幂等 | 过期触达与主对话断层 |
| 观测层 | Metrics、SLS、Langfuse、结构化日志 | 故障定位和业务追踪 |

#### 4.8.2 观测模型

主链路可按下面的关联键排查：

```text
sessionId / identityKey
  └─ requestId + revision
      ├─ modelRequestId + modelCallSequence
      ├─ activeIndustryId + policy source
      ├─ toolCallId + toolName + duration
      ├─ skillName + source
      ├─ business taskId / relayId / eventId
      └─ outbound messageId / provider requestId
```

`WecomChatService` 记录 context enrich、session claim、industry route、processor、tool side effects、memory flush、state commit 和 event emit 等阶段耗时。`AihireModelObservabilityInterceptor` 记录模型请求序号、模型名、消息数、字符估算和工具数。Harness 执行器还形成 run/task、路由模式、delegated、预算消耗和未决项等诊断字段；当前源码允许 Observer 回退为 NONE，不能仅凭字段存在声称 Harness trace 已在线上生效。SLS emitter 对统一事件字段做规范化并异步发送，异常只记录日志，不反向拖垮主对话。

Langfuse 侧将一轮业务请求映射为 trace，把模型调用映射为 generation，把工具调用映射为 span。两套观测并不重复：SLS 更适合业务事件统计与排障，Langfuse 更适合模型/工具调用链分析。但“具备观测链”不等于“正文已完全脱敏”：会话内容、身份字段和打开后的 Raw HTTP body 都必须结合当前配置、字段映射和日志样本单独审计。

当前代码还保留 Legacy 与 OpenTelemetry 两类 Langfuse 协议，通过统一配置选择主出口，并可配置 OTel 镜像双写。正确的迁移顺序是先双写对比 trace/generation/tool span 结构，再切主协议；两个出口需要故障隔离。Legacy 内存队列和任何旁路上报都属于 best-effort，不能承诺零丢失。

#### 4.8.3 指标口径

代码中已定义企微进入与回复、岗位工具、知识工具、候选人工具、LLM 成功/失败/超时与 fallback、KV Session/Memory、身份迁移等指标枚举。面试时要区分：

- “枚举和上报调用已存在”是代码事实。
- “监控平台已注册且线上有数据”需要环境配置和平台查询证明。
- 不能因为 code 已填写，就声称告警已上线或指标达到某个数值。

当前静态扫描可看到 `CwecomeMetrics` 的默认 Reporter 为 Noop，未找到明确的生产 Reporter 装配；文员补偿部分也包含进程内计数与结构化日志。因此简历可以写“建立指标门面和埋点调用点”，不能写“已经形成跨节点监控与告警闭环”。

#### 4.8.4 安全配置与敏感信息边界

当前仓库静态配置中可见历史默认凭据形态与 env 配置文件，因此面试时不能说“配置安全已经完全解决”。正确表述是：

- 任何口令、Token、AK/SK 都不进入简历、面试材料、日志样例或截图，统一写作 `[REDACTED_SECRET]`。
- 运行配置应迁移到 Secret Manager、容器 Secret 或受控环境变量，并对已经进入历史的凭据执行轮换，而不只是从当前文件删除。
- 日志默认关闭正文优于“开启后再截断”；截断只控制体积，不等于 DLP、掩码或字段级脱敏。
- SLS、Langfuse、Raw HTTP 和业务事件需要分别审计用户原文、手机号、身份 ID、岗位/群 ID 与工具参数，建立最小采集、访问控制和留存周期。
- `.env`、部署脚本和示例配置也要纳入 Git 跟踪审计，不能只扫描 Java 源码。

这类发现应作为“安全债务与改进项”陈述，不能包装成已完成治理；是否已在部署侧替换和轮换，需要配置平台与发布记录证明。

#### 4.8.5 测试策略

2026-11-05 对当前工作区做静态盘点，共找到 573 个位于 `src/test/java` 下的 Java 测试源文件，分布在 app、candidate、conversation、cron、dao、outbound、rpc、common 和工具目录。这个数字只说明测试资产规模，不说明当前全量测试已经执行或全部通过。高价值测试不是追求总数，而是覆盖边界：

- `SessionExecutionCoordinatorCriticalPhaseTest`：关键阶段下的中断与保护。
- `KvSessionStoreLockTest`：Session 锁和并发行为。
- `WecomChatServiceJobToolSessionStateTest`：选岗持久化、回滚与 direct reply。
- `RuntimePolicyContextAssemblerTest`：通用与行业 Policy 选择。
- `NacosIndustrySkillConfigClientTest`：远程配置校验与降级。
- `TagExtractTaskServiceImplTest` / `TagExtractionWorkerServiceImplTest`：任务防重、claim、批次与快照。
- `WecomFriendRelationOperationsImplTest` / `WecomFriendDispatchOperationsImplTest`：关系幂等与派发状态。
- `ReactivationDispatchServiceTest` / `ReactivationPreSendGuardTest`：发送前取消、重排与失败。
- `DefaultStaffJoinCompensationServiceTest`：文员入群确认与替换状态机。
- `AihireHarnessModeConfigurationTest`：REACT/AUTO/CHECKLIST 的启动准入与依赖校验。
- `EvaluationLegacyAutoDelegationTest` / `EvaluationInlineAutoTest`：AUTO 路由、子任务回执、静默与汇总边界。
- `TableStoreConversationMessageStoreTest`：分块历史、TTL、清理与失败语义。
- `GroupAgentAutoConfigurationTest` 及 group 模块测试：群装配、交接、租约、回复派发和上下文隔离。

Harness 评测还要守住“真实执行”和“成功判定”边界：评测入口限制为 localhost，默认不应触发真实执行，只有显式执行开关才允许运行；HTTP 接受或模型生成草稿都不是成功，至少要看到最终 `REPLY_PUBLISHED` 及对应事件链。历史对照报告只能证明当时的样本与版本，不能替代当前 checkout 或生产灰度验证。

验证金字塔建议：

```text
纯函数/策略单测
→ Service + fake repository 状态转换测试
→ DAO 条件更新与唯一约束测试
→ 模块集成测试
→ 通道沙箱与模型回放
→ 小流量生产观测
```

本文只完成静态代码证据和文档结构验证；是否所有测试当前均能构建通过，需要实际执行 Maven 后才能确认。

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

#### 4.8.11 面试官追问防守

**问：你认为当前系统还有什么不足？**

答：第一，Session 与 Memory 如果落在不同存储，当前是应用层事务语义，还可增加 commit marker 或 outbox 提升恢复能力；第二，部分跨系统动作仍依赖重试补偿，需要持续核验幂等键和终态；第三，模型与行业 Policy 的效果必须靠回放集和线上灰度指标验证，不能只看单测；第四，指标门面存在但当前仓库未发现生产 Reporter 装配，不能把埋点等同于监控闭环；第五，标签 MQ 消费异常更依赖应用侧失败状态与重新扫描，需要加强卡死告警；第六，配置凭据、外呼请求日志和观测正文仍需统一 Secret/PII 治理。

**问：你如何证明这些设计有效？**

答：我会分四层证据：代码路径证明机制存在；单元/集成测试证明关键状态转换；回放和沙箱证明模型及通道行为；生产 SLS、trace 和业务库证明线上效果。当前这份材料只引用前两类中的静态文件，线上结论必须另取数据。

**问：如果让你重新做一次，优先做什么？**

答：先定义业务事实和状态机，再设计 Agent 协议；优先建设 requestId、幂等、outbox/补偿和观测字段，然后接模型。因为模型接入通常最快，真正昂贵的是上线后无法解释或恢复的半状态。

**问：你个人最能体现架构能力的工作是什么？**

答：不是某个框架接入，而是把对话、策略、真实动作和状态提交拆成明确边界，并把同一原则复用到选岗、关系、标签、拉群和促活：模型只能在受控接口内提出动作，成功语义由确定性系统确认，失败能回滚或补偿，整个过程可追踪。

#### 4.8.12 面试前自检清单

- [ ] 能在 30 秒说清项目不是普通聊天机器人。
- [ ] 能画出 Controller → Service → Processor → Agent → Tool → State 的调用链。
- [ ] 能解释 Agent、Skill、Tool、Workflow 的判定标准。
- [ ] 能解释为什么 Session/Memory 不是业务事实库。
- [ ] 能完整讲出 latest-wins、关键阶段保护和请求级回滚。
- [ ] 能说明多行业为什么一轮只允许一份 Policy。
- [ ] 能讲清 `set_active_job` 的校验、returnDirect 和失败处理。
- [ ] 能用好友关系说明跨系统最终一致性。
- [ ] 能用标签或促活说明 claim、幂等、重试和终态。
- [ ] 能解释“建群成功”和“文员实际入群”的差别。
- [ ] 能解释 REACT、AUTO、CHECKLIST，以及为什么单轮 DIRECT/DELEGATE 不是部署模式。
- [ ] 能说明 Harness 为什么不能拿走原 owner 的状态提交和发消息权限。
- [ ] 能说明私聊到群聊为什么交接结构化摘要，而不是复制整段历史。
- [ ] 能解释 TableStore 读取失败为什么不能降级为空历史。
- [ ] 能区分代码事实、测试证据、部署配置和生产结果。
- [ ] 遇到配置凭据和日志正文问题时，只说风险与治理方案，不复制任何秘密值。
- [ ] 不背诵未经本人确认的规模、指标或团队归属。

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

#### 4.8.14 验证边界声明

本手册的事实来源是当前检出代码、POM、设计文档和测试文件。可确认的是：相关类、状态、分支和测试资产存在；不可仅据此确认的是：

- 当前生产环境是否启用了所有模块与配置开关。
- Nacos、RocketMQ、数据库、SLS、Langfuse 和外部通道的实际部署值。
- 全量 Maven 构建、模块集成测试和端到端链路是否在本次文档生成时通过。
- 线上调用规模、成功率、时延、转化率、成本或业务收益。
- 仓库全部代码是否均由个人独立完成。

面试中如被追问线上结果，应使用本人掌握的真实监控、发布记录和团队分工补充；没有证据时明确说“代码机制已落地，线上数据需要以监控平台为准”。
