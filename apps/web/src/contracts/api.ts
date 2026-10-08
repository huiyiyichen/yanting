/**
 * 本文件由 scripts/generateContracts.mjs 自动生成，请勿手工修改。
 * 来源：../../data/runtime/contracts-export/openapi.json
 * 字段命名为 camelCase，与后端 Pydantic 序列化别名一致。
 */

export interface paths {
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health/probe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Probe
         * @description 实测外部能力：真实发起一次文本补全与一次编码。
         *
         *     返回结构中的 `ok` 只表示本次实测结果，不代表验收通过。
         */
        post: operations["probe_api_health_probe_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/contracts/enums": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Enums
         * @description 全部固定枚举及其中文展示文案。
         */
        get: operations["enums_api_contracts_enums_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/contracts/manifest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Manifest */
        get: operations["manifest_api_contracts_manifest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/conversations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Conversations */
        get: operations["list_conversations_api_customer_conversations_get"];
        put?: never;
        /** Create Conversation */
        post: operations["create_conversation_api_customer_conversations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/onboarding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Onboarding
         * @description 新会话开场白的固定文案与快捷入口（唯一来源在后端）。
         *
         *     前端只在「该会话还没有客户消息」时展示快捷选项；用户不点、直接打字也走
         *     同一个发送接口与同一套编排，不做"点按钮才有的特殊分支"。
         */
        get: operations["onboarding_api_customer_onboarding_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/conversations/{conversation_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Messages */
        get: operations["list_messages_api_customer_conversations__conversation_id__messages_get"];
        put?: never;
        /**
         * Send Message
         * @description 客户发送消息并触发 Agent 处理。
         *
         *     幂等：同一 `clientMessageKey` 重复提交不追加第二条消息，也不重复调用模型。
         *     客户侧响应**不包含**内部判断明细，只返回消息本身与自动回复。
         */
        post: operations["send_message_api_customer_conversations__conversation_id__messages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/conversations/{conversation_id}/handoff": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Request Handoff */
        post: operations["request_handoff_api_customer_conversations__conversation_id__handoff_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/conversations/{conversation_id}/rating": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Rating */
        get: operations["get_rating_api_customer_conversations__conversation_id__rating_get"];
        put?: never;
        /**
         * Submit Rating
         * @description 服务结束时的 1—5 分评价，可跳过。未评价保持空值，不填默认分。
         */
        post: operations["submit_rating_api_customer_conversations__conversation_id__rating_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/vision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Vision Availability
         * @description 图片能力的真实状态。前端据此决定是否展示上传入口。
         */
        get: operations["vision_availability_api_customer_vision_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/attachments/{attachment_id}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Attachment Content
         * @description 读取附件原图。
         *
         *     存在的理由：消息里只保存附件**元数据**（避免把 base64 塞进消息、把会话响应
         *     撑大几十倍），前端靠这个地址渲染缩略图。路径只来自系统生成值，不拼接用户输入。
         */
        get: operations["attachment_content_api_customer_attachments__attachment_id__content_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/conversations/{conversation_id}/attachments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Attachment
         * @description 上传图片。
         *
         *     校验：仅 JPEG/PNG/WebP、每张不超过配置上限；**实际类型与可解码性由后端确认**，
         *     不接受扩展名或前端声明作为依据。文件只落到 `data/runtime/attachments/`。
         */
        post: operations["upload_attachment_api_customer_conversations__conversation_id__attachments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/customer/conversations/{conversation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Conversation
         * @description 删除会话及其全部依赖数据（消息、附件、案件、申请、候选）。
         *
         *     为什么允许删除：本机 Demo 会累积大量演示会话（实测数百条），没有删除入口
         *     就只能手工清库。**审计不删**：`audit_event` 是追加式追溯记录，删除动作本身
         *     也会写一条 `conversation_deleted`，否则「会话不见了」在追溯链上是空洞。
         */
        delete: operations["delete_conversation_api_customer_conversations__conversation_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Queue */
        get: operations["queue_api_support_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/service-queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Service Queue */
        get: operations["service_queue_api_support_service_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Messages */
        get: operations["list_messages_api_support_conversations__conversation_id__messages_get"];
        put?: never;
        /**
         * Send Operator Message
         * @description 客服发送消息。
         *
         *     托管期间必须先接管再发送（工程规范第 13.2 节）：
         *     这里校验服务模式，避免「暗中接管」。
         */
        post: operations["send_operator_message_api_support_conversations__conversation_id__messages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/service-context": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Service Context */
        get: operations["service_context_api_support_conversations__conversation_id__service_context_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/assistant": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Consumer Service Assistant */
        get: operations["consumer_service_assistant_api_support_conversations__conversation_id__assistant_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/risk-alerts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Risk Alerts */
        get: operations["list_risk_alerts_api_support_risk_alerts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/risk-alerts/{alert_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Risk Alert Detail */
        get: operations["risk_alert_detail_api_support_risk_alerts__alert_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/risk-alerts/{alert_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Update Risk Alert Status */
        post: operations["update_risk_alert_status_api_support_risk_alerts__alert_id__status_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/case": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Case Detail
         * @description 案件信息 + 知识依据 + 申请列表。仅客服可见。
         */
        get: operations["case_detail_api_support_conversations__conversation_id__case_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/service-mode": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Set Service Mode
         * @description 接管会话 / 恢复 AI 托管。两个方向都是独立操作。
         */
        post: operations["set_service_mode_api_support_conversations__conversation_id__service_mode_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/requests/{request_id}/review": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Review Request
         * @description 批准 / 拒绝 / 退回补充。
         *
         *     批准只表示 Demo 内的人工确认，**不代表**真实退款或换货已完成。
         *     拒绝与退回必须给出原因；旧版本的确认会被拒绝。
         */
        post: operations["review_request_api_support_requests__request_id__review_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/requests/pending": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Pending Requests
         * @description 待人工确认队列。未操作时一直在这里，无超时、无自动升级。
         */
        get: operations["pending_requests_api_support_requests_pending_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/audit/{conversation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Audit Trail
         * @description 案件相关审计轨迹（仅客服）。不返回完整 prompt/output。
         */
        get: operations["audit_trail_api_support_audit__conversation_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/health/echo": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Support Echo
         * @description 客服侧连通性检查，同时暴露契约版本便于前端对齐。
         */
        post: operations["support_echo_api_support_health_echo_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/suggestions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Suggestions
         * @description 读取当前候选。新客户消息到达后 `expires=true`，不得静默发送。
         */
        get: operations["get_suggestions_api_support_conversations__conversation_id__suggestions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/suggestions/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Generate Suggestions
         * @description 按当前上下文生成「推荐 / 简洁 / 安抚」三种措辞。
         *
         *     候选必须来自真实模型；模型不可用时返回明确错误，不提供预设文案兜底。
         */
        post: operations["generate_suggestions_api_support_conversations__conversation_id__suggestions_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/suggestions/action": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Suggestion Action
         * @description 采用或忽略候选。
         *
         *     **采用只写入客服草稿，不发送、不审批、不接管**；发送仍是独立动作。
         */
        post: operations["suggestion_action_api_support_conversations__conversation_id__suggestions_action_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Conversation Support
         * @description 客服侧删除会话（清理演示数据用）。与客户侧走同一条仓储逻辑。
         */
        delete: operations["delete_conversation_support_api_support_conversations__conversation_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/conversations/{conversation_id}/close": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Close Conversation
         * @description 结束服务并开放评价入口。
         *
         *     为什么把「结束」和「请求评价」放在一起：PRD 5.2 规定评价在**服务结束时**发起，
         *     分成两步会留下「关了但评价入口没开」的中间态，客户页面上什么都看不到。
         */
        post: operations["close_conversation_api_support_conversations__conversation_id__close_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Model Config
         * @description 模型配置一览：真实配置 + 真实健康状态 + 网关可用模型列表。
         */
        get: operations["model_config_api_platform_models_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/models/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Model
         * @description 对某个模型发一次极小请求，如实返回成功或错误原因。
         */
        post: operations["test_model_api_platform_models_test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/rerank/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Rerank
         * @description 对当前重排序配置发一次真实请求，如实返回排序结果或失败原因。
         *
         *     用两句**与查询一强一弱**的固定样例：只回"连通"不能证明它真的在排序，
         *     因此把两句的先后顺序一起回给页面。
         */
        post: operations["test_rerank_api_platform_rerank_test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Knowledge Overview
         * @description 知识库总览：当前快照、切片配置、编码模型与逐文档状态。
         *
         *     数据全部来自真实的 knowledge_* 表：文档的解析/索引状态用表里的
         *     parse_status / index_status，片段数用文档行上的 chunk_count
         *     （knowledge_chunk 没有 snapshot 列，按快照再聚合一次是错的）。
         */
        get: operations["knowledge_overview_api_platform_knowledge_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/work-orders": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Work Orders
         * @description 工单管理视图。
         *
         *     本期没有独立的「工单」实体：一条售后工单就是「会话 + 案件」。这里按
         *     会话维度聚合真实数据，不新造实体、也不提供不存在的操作（如派单、改单）。
         */
        get: operations["work_orders_api_platform_work_orders_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/prompts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Prompt List
         * @description 当前真正生效的提示词一览（只读）。
         *
         *     为什么要暴露：模型的行为由提示词决定，改提示词是改行为。本期提示词仍是
         *     代码常量（版本号随代码走），因此这里**如实展示**内容与版本，并提供复制；
         *     可编辑/启停需要模板表与版本化，已登记为下一步（DEV-027），不做只能点不能用的假按钮。
         */
        get: operations["prompt_list_api_platform_prompts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/models/active": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Switch Active Model
         * @description 把生效的文本模型切换成另一个，并**持久化**（重启后仍生效）。
         *
         *     只允许切到「网关确实提供」的模型：否则会把整个 Demo 切到一个不存在的模型上，
         *     之后所有对话都失败——那比不让切更糟。
         */
        post: operations["switch_active_model_api_platform_models_active_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/prompt-templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Prompt Templates
         * @description 提示词模板列表（含内置模板，已从代码常量播种）。
         */
        get: operations["list_prompt_templates_api_platform_prompt_templates_get"];
        put?: never;
        /**
         * Create Prompt Template
         * @description 新增模板。`code` 唯一：同一个用途只允许一条，避免「到底用哪条」说不清。
         */
        post: operations["create_prompt_template_api_platform_prompt_templates_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/prompt-templates/{template_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Prompt Template
         * @description 编辑模板内容：每次改动 `revision` 自增，便于追溯「当时用的是哪一版」。
         */
        put: operations["update_prompt_template_api_platform_prompt_templates__template_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/prompt-templates/{template_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Set Prompt Status
         * @description 启用 / 停用模板。停用后 Agent 回退到**代码常量**（不是空提示词）。
         */
        post: operations["set_prompt_status_api_platform_prompt_templates__template_id__status_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/prompt-templates/{template_id}/binding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bind Prompt */
        post: operations["bind_prompt_api_platform_prompt_templates__template_id__binding_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/prompt-templates/{template_id}/revisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Prompt Revisions */
        get: operations["prompt_revisions_api_platform_prompt_templates__template_id__revisions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/prompt-templates/{template_id}/restore": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Restore Prompt */
        post: operations["restore_prompt_api_platform_prompt_templates__template_id__restore_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/models/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Save Model Config
         * @description 保存模型配置（地址 / 密钥 / 文本模型 / 多模态模型）。
         *
         *     三条约定：
         *     1. **密钥只进不出**：保存后返回的是掩码，页面永远拿不到原文；
         *     2. 立即生效并持久化到 `runtime_setting`（重启由启动流程套用）；
         *     3. 保存后**立刻做一次连通性测试**，把真实结果放在 `message` 里——
         *        否则用户以为配好了，实际下一句对话就失败。
         */
        put: operations["save_model_config_api_platform_models_config_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge-bases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Knowledge Bases
         * @description 知识库列表：每个库的文档数与片段数（真实聚合，供左侧列表）。
         */
        get: operations["knowledge_bases_api_platform_knowledge_bases_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Queue */
        get: operations["queue_api_support_reception_queue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/{conversation_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Messages */
        get: operations["messages_api_support_reception__conversation_id__messages_get"];
        put?: never;
        /** Send */
        post: operations["send_api_support_reception__conversation_id__messages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/{conversation_id}/attachments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Upload Attachment */
        post: operations["upload_attachment_api_support_reception__conversation_id__attachments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/{conversation_id}/seen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Seen */
        post: operations["seen_api_support_reception__conversation_id__seen_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/{conversation_id}/assistant": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate */
        post: operations["generate_api_support_reception__conversation_id__assistant_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/{conversation_id}/memory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Service Memory */
        get: operations["service_memory_api_support_reception__conversation_id__memory_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/{conversation_id}/suggestion-action": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Suggestion Action */
        post: operations["suggestion_action_api_support_reception__conversation_id__suggestion_action_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/work-orders/all": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Work Orders */
        get: operations["work_orders_api_support_reception_work_orders_all_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/reception/{conversation_id}/service-mode": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Set Mode */
        post: operations["set_mode_api_support_reception__conversation_id__service_mode_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/operators": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Operator Roster */
        get: operations["operator_roster_api_support_desk_operators_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Stats */
        get: operations["stats_api_support_desk_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/tickets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ticket List */
        get: operations["ticket_list_api_support_desk_tickets_get"];
        put?: never;
        /** Ticket Create */
        post: operations["ticket_create_api_support_desk_tickets_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/tickets/{ticket_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ticket Detail */
        get: operations["ticket_detail_api_support_desk_tickets__ticket_id__get"];
        /** Ticket Update */
        put: operations["ticket_update_api_support_desk_tickets__ticket_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/risks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Risk List */
        get: operations["risk_list_api_support_desk_risks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/conversations/{conversation_id}/risks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Conversation Risks */
        get: operations["conversation_risks_api_support_desk_conversations__conversation_id__risks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/risks/scan": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Risk Scan */
        post: operations["risk_scan_api_support_desk_risks_scan_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/risk-judgments/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Risk Judgment Export */
        get: operations["risk_judgment_export_api_support_desk_risk_judgments_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/risks/{incident_id}/signals/{alert_id}/judgment": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Risk Judgment */
        post: operations["risk_judgment_api_support_desk_risks__incident_id__signals__alert_id__judgment_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/breakpoints/{conversation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Breakpoint Assessment */
        get: operations["breakpoint_assessment_api_support_desk_breakpoints__conversation_id__get"];
        put?: never;
        /** Breakpoint Analyze */
        post: operations["breakpoint_analyze_api_support_desk_breakpoints__conversation_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/risks/{incident_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Risk Detail */
        get: operations["risk_detail_api_support_desk_risks__incident_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/risks/{incident_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Risk Update */
        post: operations["risk_update_api_support_desk_risks__incident_id__status_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/support/desk/risks/{incident_id}/intervene": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Risk Intervene */
        post: operations["risk_intervene_api_support_desk_risks__incident_id__intervene_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Documents */
        get: operations["documents_api_platform_knowledge_documents_get"];
        put?: never;
        /** Create Document */
        post: operations["create_document_api_platform_knowledge_documents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge/products": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Products */
        get: operations["products_api_platform_knowledge_products_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge/documents/{document_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Document */
        get: operations["document_api_platform_knowledge_documents__document_id__get"];
        /** Save Document */
        put: operations["save_document_api_platform_knowledge_documents__document_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge/bases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Base */
        post: operations["create_base_api_platform_knowledge_bases_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge/documents/{document_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Toggle Document */
        post: operations["toggle_document_api_platform_knowledge_documents__document_id__status_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge/publish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish */
        post: operations["publish_api_platform_knowledge_publish_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/platform/knowledge/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Search */
        post: operations["search_api_platform_knowledge_search_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AgentDecisionView */
        AgentDecisionView: {
            conversationStage: components["schemas"]["ConversationStage"];
            /** Serviceroute */
            serviceRoute: string;
            /** Customerintents */
            customerIntents?: components["schemas"]["CustomerIntent"][];
            emotionLevel: components["schemas"]["EmotionLevel"];
            complaintRisk: components["schemas"]["ComplaintRisk"];
            /** Missingfacts */
            missingFacts?: string[];
            /** Productcandidates */
            productCandidates?: {
                [key: string]: unknown;
            }[];
            /** Knowledgehitstatus */
            knowledgeHitStatus?: string | null;
            /** Retrievalid */
            retrievalId?: string | null;
            /** Warrantystatus */
            warrantyStatus?: string | null;
            /** Dealerauthorizationstatus */
            dealerAuthorizationStatus?: string | null;
            /** Requestdraft */
            requestDraft?: {
                [key: string]: unknown;
            } | null;
            /**
             * Humaninterventionrequired
             * @default false
             */
            humanInterventionRequired: boolean;
            /** Humaninterventionreason */
            humanInterventionReason?: string | null;
            caseStatus: components["schemas"]["CaseStatus"];
            /**
             * Ratingrequested
             * @default false
             */
            ratingRequested: boolean;
            /** Notes */
            notes?: string[];
            /** Toolcalls */
            toolCalls?: {
                [key: string]: unknown;
            }[];
            /** Modelid */
            modelId?: string | null;
            /** Promptversion */
            promptVersion?: string | null;
        };
        /** AssistantActionRequest */
        AssistantActionRequest: {
            /** Inputhash */
            inputHash: string;
            /** Style */
            style: string;
            /** Action */
            action: string;
        };
        /** AssistantReplySuggestionView */
        AssistantReplySuggestionView: {
            /** Style */
            style: string;
            /** Body */
            body: string;
            /** Claims */
            claims?: components["schemas"]["GroundingClaim"][];
            /** Empathydimensions */
            empathyDimensions?: components["schemas"]["ReplyEmpathyDimension"][];
        };
        /** AttachmentView */
        AttachmentView: {
            /** Attachmentid */
            attachmentId: string;
            /** Conversationid */
            conversationId: string;
            /** Messageid */
            messageId?: string | null;
            /** Mimetype */
            mimeType: string;
            /** Bytesize */
            byteSize: number;
            /** Width */
            width?: number | null;
            /** Height */
            height?: number | null;
            /** Sha256 */
            sha256: string;
            /** Createdat */
            createdAt: string;
        };
        /** Body_upload_attachment_api_customer_conversations__conversation_id__attachments_post */
        Body_upload_attachment_api_customer_conversations__conversation_id__attachments_post: {
            /**
             * File
             * Format: binary
             */
            file: string;
        };
        /** Body_upload_attachment_api_support_reception__conversation_id__attachments_post */
        Body_upload_attachment_api_support_reception__conversation_id__attachments_post: {
            /**
             * File
             * Format: binary
             */
            file: string;
        };
        /** BreakpointEvidence */
        BreakpointEvidence: {
            /** Sourceref */
            sourceRef: string;
            /** Quote */
            quote: string;
            /** Kind */
            kind: string;
            /** Label */
            label: string;
            /** Occurredat */
            occurredAt?: string | null;
            /** Conversationid */
            conversationId?: string | null;
        };
        /**
         * CapabilityStatus
         * @description 单项外部能力的真实状态。
         */
        CapabilityStatus: {
            /** Name */
            name: string;
            /**
             * State
             * @enum {string}
             */
            state: "ready" | "unavailable" | "unknown";
            /** Detail */
            detail: string;
            /** Modelid */
            modelId?: string | null;
            /** Revision */
            revision?: string | null;
        };
        /**
         * CaseStatus
         * @description 案件办理状态。`open`/`awaiting_user`/`pending_review`/`closed`。
         *
         *     注意：`closed` 只表示流程结束，不等于设备修好或业务已履行。
         * @enum {string}
         */
        CaseStatus: "open" | "awaiting_user" | "pending_review" | "closed";
        /**
         * CaseView
         * @description 案件信息（客服侧）。客户侧不返回该结构。
         */
        CaseView: {
            /** Caseid */
            caseId: string;
            /** Conversationid */
            conversationId: string;
            caseStatus: components["schemas"]["CaseStatus"];
            conversationStage: components["schemas"]["ConversationStage"];
            /** Productid */
            productId?: string | null;
            /** Productmodel */
            productModel?: string | null;
            /** Productcategory */
            productCategory?: string | null;
            /** Countrycode */
            countryCode?: string | null;
            /** Purchasechannel */
            purchaseChannel?: string | null;
            /** Sellernameraw */
            sellerNameRaw?: string | null;
            /** Sellernamestandard */
            sellerNameStandard?: string | null;
            /** Customerintents */
            customerIntents?: components["schemas"]["CustomerIntent"][];
            emotionLevel: components["schemas"]["EmotionLevel"];
            complaintRisk: components["schemas"]["ComplaintRisk"];
            /** Warrantystatus */
            warrantyStatus?: string | null;
            /** Dealerauthorizationstatus */
            dealerAuthorizationStatus?: string | null;
            /** Knowledgehitstatus */
            knowledgeHitStatus?: string | null;
            /** Retrievalid */
            retrievalId?: string | null;
            /** Troubleshootingresult */
            troubleshootingResult: string;
            ratingStatus: components["schemas"]["RatingStatus"];
            /** Userrating */
            userRating?: number | null;
            /** Missingfacts */
            missingFacts?: string[];
            /** Observedfromimage */
            observedFromImage?: string[];
            /** Evidence */
            evidence?: components["schemas"]["EvidenceView"][];
            /** Requests */
            requests?: components["schemas"]["RequestView"][];
            /** Allowedactions */
            allowedActions?: string[];
            /** Forbiddenactions */
            forbiddenActions?: string[];
            /** Servicestartedat */
            serviceStartedAt: string;
            /** Updatedat */
            updatedAt: string;
        };
        /** CloseConversationRequest */
        CloseConversationRequest: {
            /**
             * Reason
             * @default
             */
            reason: string;
        };
        /** CloseConversationView */
        CloseConversationView: {
            /** Conversationid */
            conversationId: string;
            /** Caseid */
            caseId: string;
            /** Casestatus */
            caseStatus: string;
            /** Ratingstatus */
            ratingStatus: string;
            /** Message */
            message: string;
        };
        /**
         * ComplaintRisk
         * @description 投诉风险，与情绪分开记录。
         * @enum {string}
         */
        ComplaintRisk: "flagged" | "not_flagged" | "unknown";
        /** ConsumerHistoryView */
        ConsumerHistoryView: {
            /** Conversationid */
            conversationId: string;
            /** Firstat */
            firstAt?: string | null;
            /** Lastat */
            lastAt?: string | null;
            /**
             * Latestcustomermessage
             * @default
             */
            latestCustomerMessage: string;
            /**
             * Lateststaffmessage
             * @default
             */
            latestStaffMessage: string;
            /** Orderids */
            orderIds?: string[];
            /** Workorderids */
            workOrderIds?: string[];
            /**
             * Relation
             * @default historical
             * @enum {string}
             */
            relation: "same_order" | "historical";
            /** Sametopic */
            sameTopic?: boolean | null;
        };
        /** ConsumerServiceAssistantView */
        ConsumerServiceAssistantView: {
            /** Observationid */
            observationId: string;
            /** Datasetid */
            datasetId: string;
            /** Batchid */
            batchId: string;
            /** Conversationid */
            conversationId: string;
            /** Currentquestion */
            currentQuestion: string;
            /** Servicesummary */
            serviceSummary: string;
            emotionLevel: components["schemas"]["EmotionLevel"];
            emotionTrend: components["schemas"]["EmotionTrend"];
            /** Risktypes */
            riskTypes: components["schemas"]["ServiceRiskType"][];
            riskLevel: components["schemas"]["ServiceRiskLevel"];
            riskStatus: components["schemas"]["ServiceRiskStatus"];
            /** Riskreason */
            riskReason: string;
            /** Evidencerefs */
            evidenceRefs: string[];
            /** Missinginformation */
            missingInformation: string[];
            /** Nextsteps */
            nextSteps: string[];
            /** Replysuggestions */
            replySuggestions: components["schemas"]["AssistantReplySuggestionView"][];
            /**
             * Adoptedcount
             * @default 0
             */
            adoptedCount: number;
            /** Personalizedadvice */
            personalizedAdvice?: components["schemas"]["PersonalizedAdviceView"][];
            /** Ismock */
            isMock: boolean;
            /** Modelid */
            modelId: string;
            /** Promptversion */
            promptVersion: string;
            /**
             * Inputhash
             * @default
             */
            inputHash: string;
            /**
             * Stale
             * @default false
             */
            stale: boolean;
            /**
             * Knowledgestatus
             * @default not_found
             */
            knowledgeStatus: string;
            /** Knowledgeevidence */
            knowledgeEvidence?: {
                [key: string]: unknown;
            }[];
            /**
             * Handoffrequired
             * @default false
             */
            handoffRequired: boolean;
            /**
             * Deliverymode
             * @default draft
             */
            deliveryMode: string;
            /** Memoryitems */
            memoryItems?: components["schemas"]["MemoryItem"][];
            /** Groundingsources */
            groundingSources?: components["schemas"]["GroundingSource"][];
            /**
             * Verificationstatus
             * @default unverified
             */
            verificationStatus: string;
            /** Workflowsteps */
            workflowSteps?: components["schemas"]["WorkflowStep"][];
            /** Modelusage */
            modelUsage?: {
                [key: string]: unknown;
            };
            /**
             * Intent
             * @default unknown
             */
            intent: string;
            /** Servicebreakpoints */
            serviceBreakpoints?: components["schemas"]["ServiceBreakpointView"][] | null;
        };
        /** ConsumerServiceContextView */
        ConsumerServiceContextView: {
            /** Datasetid */
            datasetId: string;
            /** Batchid */
            batchId: string;
            /** Conversationid */
            conversationId: string;
            /** Buyeralias */
            buyerAlias: string;
            /** Buyeraliases */
            buyerAliases: string[];
            /** Firstat */
            firstAt?: string | null;
            /** Lastat */
            lastAt?: string | null;
            /** Orders */
            orders: components["schemas"]["ServiceOrderView"][];
            /** Workorders */
            workOrders: components["schemas"]["ServiceWorkOrderView"][];
            /** Timeline */
            timeline: components["schemas"]["ServiceTimelineEventView"][];
            /** Products */
            products?: components["schemas"]["ServiceProductView"][];
            /** Servicenodes */
            serviceNodes?: components["schemas"]["ServiceNodeView"][];
            /** Historyconversationids */
            historyConversationIds?: string[];
            /** Historyservices */
            historyServices?: components["schemas"]["ConsumerHistoryView"][];
        };
        /**
         * ConversationStage
         * @description 会话当前所处的处理阶段（程序状态，不是渲染视角）。
         * @enum {string}
         */
        ConversationStage: "new" | "intake" | "disambiguation" | "diagnosis" | "eligibility" | "awaiting_confirmation" | "closure" | "rating" | "closed";
        /** ConversationSummary */
        ConversationSummary: {
            /** Conversationid */
            conversationId: string;
            /** Title */
            title: string;
            /** Customerid */
            customerId: string;
            serviceMode: components["schemas"]["ServiceMode"];
            /** Messagerevision */
            messageRevision: number;
            /** Moderevision */
            modeRevision: number;
            /**
             * Lastmessagepreview
             * @default
             */
            lastMessagePreview: string;
            /**
             * Messagecount
             * @default 0
             */
            messageCount: number;
            caseStatus?: components["schemas"]["CaseStatus"] | null;
            /**
             * Autoreplystatus
             * @default idle
             */
            autoReplyStatus: string;
        };
        /** CreateConversationRequest */
        CreateConversationRequest: {
            /**
             * Customerid
             * @default CUST-DEMO-01
             */
            customerId: string;
            /** Title */
            title?: string | null;
        };
        /** CreatePromptRequest */
        CreatePromptRequest: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /**
             * Scenario
             * @default
             */
            scenario: string;
            /** Content */
            content: string;
        };
        /**
         * CustomerIntent
         * @description 固定客户意图。允许 unknown，不允许自由文本替代。
         * @enum {string}
         */
        CustomerIntent: "diagnosis" | "warranty_check" | "repair" | "parts" | "replacement" | "refund" | "complaint" | "progress_check" | "unknown";
        /** DemoOperatorRosterView */
        DemoOperatorRosterView: {
            /** Defaultoperatorid */
            defaultOperatorId: string;
            /** Operators */
            operators: components["schemas"]["DemoOperatorView"][];
        };
        /** DemoOperatorView */
        DemoOperatorView: {
            /** Operatorid */
            operatorId: string;
            /** Name */
            name: string;
        };
        /** DocumentMetadata */
        DocumentMetadata: {
            /**
             * Scope
             * @default document_context
             * @enum {string}
             */
            scope: "document_context" | "general_consumer" | "product_specific";
            /** Productsku */
            productSku?: string | null;
            /**
             * Productname
             * @default
             */
            productName: string;
            /** Productaliases */
            productAliases?: string[];
            /**
             * Market
             * @default unknown
             * @enum {string}
             */
            market: "CN" | "US" | "unknown";
            /**
             * Provenance
             * @default user_supplied
             * @enum {string}
             */
            provenance: "user_supplied" | "official_reference" | "team_fictional";
            /**
             * Sourcelabel
             * @default
             */
            sourceLabel: string;
            /**
             * Sourceurl
             * @default
             */
            sourceUrl: string;
        };
        /**
         * EmotionLevel
         * @description 情绪等级。只影响沟通策略，不改变质保或赔付规则。
         * @enum {string}
         */
        EmotionLevel: "calm" | "dissatisfied" | "angry" | "unknown";
        /**
         * EmotionTrend
         * @description 消费者消息情绪趋势。
         * @enum {string}
         */
        EmotionTrend: "stable" | "rising" | "falling" | "repeated" | "unknown";
        /**
         * EvidenceView
         * @description 知识依据。只暴露来源定位与摘录，不暴露内部提示词或工具日志。
         */
        EvidenceView: {
            /** Retrievalid */
            retrievalId: string;
            /** Snapshotid */
            snapshotId: string;
            /** Chunkid */
            chunkId: string;
            /** Documentid */
            documentId: string;
            /** Documenttitle */
            documentTitle: string;
            /** Documentversion */
            documentVersion: string;
            /** Knowledgebaseid */
            knowledgeBaseId: string;
            /** Visibility */
            visibility: string;
            /** Headingpath */
            headingPath: string;
            /** Sourcelocator */
            sourceLocator: string;
            /** Quotedexcerpt */
            quotedExcerpt: string;
            /** Applicability */
            applicability?: {
                [key: string]: unknown;
            };
            /** Channelranks */
            channelRanks?: {
                [key: string]: unknown;
            };
            /** Rrfscore */
            rrfScore: number;
        };
        /** GroundingClaim */
        GroundingClaim: {
            /** Text */
            text: string;
            /** Sourcerefs */
            sourceRefs: string[];
        };
        /** GroundingSource */
        GroundingSource: {
            /** Sourceid */
            sourceId: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "order" | "work_order" | "followup" | "customer_message" | "staff_message" | "knowledge" | "image_observation";
            /** Subjectid */
            subjectId: string;
            /** Label */
            label: string;
            /** Text */
            text: string;
            /** Occurredat */
            occurredAt?: string | null;
            /** Fields */
            fields?: {
                [key: string]: unknown;
            };
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "degraded";
            /**
             * Runmode
             * @enum {string}
             */
            runMode: "live" | "mock";
            /** Contractversion */
            contractVersion: string;
            /** Appversion */
            appVersion: string;
            database: components["schemas"]["CapabilityStatus"];
            llm: components["schemas"]["CapabilityStatus"];
            vision: components["schemas"]["CapabilityStatus"];
            embedding: components["schemas"]["CapabilityStatus"];
            knowledgeIndex: components["schemas"]["CapabilityStatus"];
            rerank: components["schemas"]["CapabilityStatus"];
        };
        /** KnowledgeBaseCreateRequest */
        KnowledgeBaseCreateRequest: {
            /** Name */
            name: string;
        };
        /** KnowledgeBaseItem */
        KnowledgeBaseItem: {
            /** Knowledgebaseid */
            knowledgeBaseId: string;
            /** Name */
            name: string;
            /** Sourcetype */
            sourceType: string;
            /** Enabled */
            enabled: boolean;
            /** Documentcount */
            documentCount: number;
            /** Chunkcount */
            chunkCount: number;
        };
        /** KnowledgeChunkView */
        KnowledgeChunkView: {
            /** Locator */
            locator: string;
            /** Text */
            text: string;
            /** Charcount */
            charCount: number;
        };
        /** KnowledgeDocumentItem */
        KnowledgeDocumentItem: {
            /** Documentid */
            documentId: string;
            /**
             * Knowledgebaseid
             * @default
             */
            knowledgeBaseId: string;
            /** Title */
            title: string;
            /** Filename */
            fileName: string;
            /** Visibility */
            visibility: string;
            /** Version */
            version: string;
            /** Status */
            status: string;
            /** Chunkcount */
            chunkCount: number;
            /** Updatedat */
            updatedAt: string;
        };
        /** KnowledgeEditRequest */
        KnowledgeEditRequest: {
            /** Title */
            title: string;
            /** Content */
            content: string;
            /**
             * Knowledgebaseid
             * @default loreal-service
             */
            knowledgeBaseId: string;
            /**
             * Expectedrevision
             * @default 0
             */
            expectedRevision: number;
            metadata?: components["schemas"]["DocumentMetadata"] | null;
        };
        /** KnowledgeEditorView */
        KnowledgeEditorView: {
            /** Documentid */
            documentId: string;
            /** Knowledgebaseid */
            knowledgeBaseId: string;
            /** Title */
            title: string;
            /** Content */
            content: string;
            /** Revision */
            revision: number;
            /** Status */
            status: string;
            /** Enabled */
            enabled: boolean;
            /** Error */
            error?: string | null;
            /** Chunks */
            chunks: components["schemas"]["KnowledgeChunkView"][];
            metadata?: components["schemas"]["DocumentMetadata"];
        };
        /** KnowledgeOverviewWithBasesView */
        KnowledgeOverviewWithBasesView: {
            /** Snapshotid */
            snapshotId?: string | null;
            /** Chunkconfigversion */
            chunkConfigVersion?: string | null;
            /**
             * Chunkcount
             * @default 0
             */
            chunkCount: number;
            /** Embeddingmodel */
            embeddingModel: string;
            /** Vectordimension */
            vectorDimension: number;
            /** Documents */
            documents?: components["schemas"]["KnowledgeDocumentItem"][];
            /**
             * Note
             * @default
             */
            note: string;
            /**
             * Chunksize
             * @default 0
             */
            chunkSize: number;
            /**
             * Chunkoverlap
             * @default 0
             */
            chunkOverlap: number;
            /** Knowledgebases */
            knowledgeBases?: components["schemas"]["KnowledgeBaseItem"][];
        };
        /** KnowledgeProductView */
        KnowledgeProductView: {
            /** Sku */
            sku: string;
            /** Name */
            name: string;
            /**
             * Identitykind
             * @default official_fixture
             */
            identityKind: string;
            /**
             * Market
             * @default CN
             */
            market: string;
            /**
             * Brand
             * @default
             */
            brand: string;
            /**
             * Sourceurl
             * @default
             */
            sourceUrl: string;
            /**
             * Imageurl
             * @default
             */
            imageUrl: string;
            /** Aliases */
            aliases?: string[];
        };
        /** KnowledgePublishView */
        KnowledgePublishView: {
            /** Ok */
            ok: boolean;
            /** Snapshotid */
            snapshotId?: string | null;
            /**
             * Chunkcount
             * @default 0
             */
            chunkCount: number;
            /** Message */
            message: string;
        };
        /** KnowledgeSearchRequest */
        KnowledgeSearchRequest: {
            /** Query */
            query: string;
            /** Knowledgebaseid */
            knowledgeBaseId?: string | null;
            /** Productsku */
            productSku?: string | null;
        };
        /** KnowledgeSearchView */
        KnowledgeSearchView: {
            /** Hitstatus */
            hitStatus: string;
            /** Snapshotid */
            snapshotId: string | null;
            /** Evidence */
            evidence: components["schemas"]["RetrievalEvidence"][];
        };
        /** KnowledgeToggleRequest */
        KnowledgeToggleRequest: {
            /** Enabled */
            enabled: boolean;
        };
        /** LogisticsTicketDetail */
        LogisticsTicketDetail: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "logistics";
            /**
             * Issuetype
             * @enum {string}
             */
            issueType: "tracking_query" | "stalled" | "not_received" | "damaged" | "address_review";
            /** Reason */
            reason: string;
            /**
             * Carrier
             * @default
             */
            carrier: string;
            /**
             * Trackingno
             * @default
             */
            trackingNo: string;
        };
        /** MemoryItem */
        MemoryItem: {
            /**
             * Category
             * @enum {string}
             */
            category: "known" | "concern" | "attempted" | "unresolved";
            /** Sourceref */
            sourceRef: string;
            /** Quote */
            quote: string;
            /**
             * Label
             * @default
             */
            label: string;
        };
        /**
         * MessageView
         * @description 消息。发送方持久化记录，渲染方向由当前视角计算，数据本身不翻转。
         */
        MessageView: {
            /** Messageid */
            messageId: string;
            /** Conversationid */
            conversationId: string;
            senderRole: components["schemas"]["SenderRole"];
            /** Body */
            body: string;
            /** Messagerevision */
            messageRevision: number;
            /** Attachments */
            attachments?: {
                [key: string]: unknown;
            }[];
            /** Createdat */
            createdAt: string;
        };
        /** ModelConfigView */
        ModelConfigView: {
            /** Gatewayhost */
            gatewayHost?: string | null;
            /** Runmode */
            runMode: string;
            /**
             * Baseurl
             * @default
             */
            baseUrl: string;
            /**
             * Apikeymasked
             * @default
             */
            apiKeyMasked: string;
            /**
             * Hasapikey
             * @default false
             */
            hasApiKey: boolean;
            /** Textmodel */
            textModel?: string | null;
            /** Visionmodel */
            visionModel?: string | null;
            /**
             * Embeddingbackend
             * @default onnx-local
             */
            embeddingBackend: string;
            /** Embeddingmodel */
            embeddingModel?: string | null;
            /**
             * Embeddingpath
             * @default
             */
            embeddingPath: string;
            /**
             * Embeddingbaseurl
             * @default
             */
            embeddingBaseUrl: string;
            /**
             * Embeddingapikeymasked
             * @default
             */
            embeddingApiKeyMasked: string;
            /**
             * Hasembeddingapikey
             * @default false
             */
            hasEmbeddingApiKey: boolean;
            /** Embeddingdimension */
            embeddingDimension?: number | null;
            /**
             * Rerankbackend
             * @default none
             */
            rerankBackend: string;
            /**
             * Rerankbaseurl
             * @default
             */
            rerankBaseUrl: string;
            /**
             * Rerankapikeymasked
             * @default
             */
            rerankApiKeyMasked: string;
            /**
             * Hasrerankapikey
             * @default false
             */
            hasRerankApiKey: boolean;
            /** Rerankmodel */
            rerankModel?: string | null;
            /** Embeddingmodeloptions */
            embeddingModelOptions?: string[];
            /** Rerankmodeloptions */
            rerankModelOptions?: string[];
            /** Availablemodels */
            availableModels?: string[];
            /**
             * Gatewaynote
             * @default
             */
            gatewayNote: string;
            /** Providers */
            providers?: components["schemas"]["ModelProviderView"][];
        };
        /**
         * ModelProviderView
         * @description 一行模型配置。`state` 与 `/api/health` 的能力状态同源。
         */
        ModelProviderView: {
            /** Key */
            key: string;
            /** Label */
            label: string;
            /** Provider */
            provider: string;
            /** Model */
            model?: string | null;
            /** State */
            state: string;
            /** Detail */
            detail: string;
            /**
             * Wired
             * @default true
             */
            wired: boolean;
            /**
             * Note
             * @default
             */
            note: string;
        };
        /**
         * OnboardingView
         * @description 新会话开场白的固定文案与快捷入口（唯一来源在后端）。
         */
        OnboardingView: {
            /** Greeting */
            greeting: string;
            /** Quickreplies */
            quickReplies: components["schemas"]["QuickReplyView"][];
        };
        /** PaymentTicketDetail */
        "PaymentTicketDetail-Input": {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "offline_payment";
            /**
             * Paymenttype
             * @enum {string}
             */
            paymentType: "refund" | "price_adjustment" | "compensation";
            /** Requestedamount */
            requestedAmount: number | string;
            /** Reason */
            reason: string;
        };
        /** PaymentTicketDetail */
        "PaymentTicketDetail-Output": {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "offline_payment";
            /**
             * Paymenttype
             * @enum {string}
             */
            paymentType: "refund" | "price_adjustment" | "compensation";
            /** Requestedamount */
            requestedAmount: string;
            /** Reason */
            reason: string;
        };
        /** PersonalizedAdviceEvidence */
        PersonalizedAdviceEvidence: {
            /** Sourceref */
            sourceRef: string;
            /** Label */
            label: string;
            /** Quote */
            quote: string;
            /** Kind */
            kind: string;
        };
        /** PersonalizedAdviceView */
        PersonalizedAdviceView: {
            /**
             * Category
             * @enum {string}
             */
            category: "routine" | "makeup" | "product_selection" | "trial_safety";
            /** Title */
            title: string;
            /** Action */
            action: string;
            /** Rationale */
            rationale: string;
            /**
             * Scope
             * @default general_consumer
             * @enum {string}
             */
            scope: "general_consumer" | "product_specific";
            /** Productsku */
            productSku?: string | null;
            /** Productname */
            productName?: string | null;
            /** Evidence */
            evidence?: components["schemas"]["PersonalizedAdviceEvidence"][];
            /** Claims */
            claims?: components["schemas"]["GroundingClaim"][];
        };
        /** PromptBindingRequest */
        PromptBindingRequest: {
            /** Purpose */
            purpose: string;
        };
        /** PromptItem */
        PromptItem: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Scenario */
            scenario: string;
            /** Version */
            version: string;
            /** Source */
            source: string;
            /** Content */
            content: string;
            /**
             * Editable
             * @default false
             */
            editable: boolean;
            /**
             * Note
             * @default
             */
            note: string;
        };
        /** PromptListView */
        PromptListView: {
            /** Items */
            items?: components["schemas"]["PromptItem"][];
            /**
             * Note
             * @default
             */
            note: string;
        };
        /** PromptRestoreRequest */
        PromptRestoreRequest: {
            /** Revision */
            revision: number;
            /** Expectedrevision */
            expectedRevision: number;
        };
        /** PromptRevisionView */
        PromptRevisionView: {
            /** Revision */
            revision: number;
            /** Content */
            content: string;
            /** Name */
            name: string;
            /** Scenario */
            scenario: string;
            /** Createdat */
            createdAt: string;
        };
        /** PromptStatusRequest */
        PromptStatusRequest: {
            /** Status */
            status: string;
        };
        /** PromptTemplateView */
        PromptTemplateView: {
            /** Templateid */
            templateId: string;
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Scenario */
            scenario: string;
            /** Content */
            content: string;
            /** Status */
            status: string;
            /** Revision */
            revision: number;
            /** Isbuiltin */
            isBuiltin: boolean;
            /** Updatedby */
            updatedBy: string;
            /** Updatedat */
            updatedAt: string;
            /** Boundpurposes */
            boundPurposes?: string[];
        };
        /** QueueItem */
        QueueItem: {
            /** Conversationid */
            conversationId: string;
            /** Caseid */
            caseId?: string | null;
            /** Title */
            title: string;
            /** Customerid */
            customerId: string;
            caseStatus?: components["schemas"]["CaseStatus"] | null;
            serviceMode: components["schemas"]["ServiceMode"];
            emotionLevel?: components["schemas"]["EmotionLevel"] | null;
            complaintRisk?: components["schemas"]["ComplaintRisk"] | null;
            /**
             * Pendingrequestcount
             * @default 0
             */
            pendingRequestCount: number;
            /** Updatedat */
            updatedAt: string;
            /**
             * Datasource
             * @default demo
             */
            dataSource: string;
        };
        /**
         * QuickReplyView
         * @description 一个快捷入口：按钮文字 + 点击后真正发出的那句话。
         */
        QuickReplyView: {
            /** Label */
            label: string;
            /** Prompt */
            prompt: string;
        };
        /** RatingRequest */
        RatingRequest: {
            /** Action */
            action: string;
            /** Rating */
            rating?: number | null;
        };
        /**
         * RatingStatus
         * @description 满意度环节状态。
         * @enum {string}
         */
        RatingStatus: "not_requested" | "pending" | "submitted" | "skipped";
        /** RatingView */
        RatingView: {
            /** Caseid */
            caseId: string;
            ratingStatus: components["schemas"]["RatingStatus"];
            /** Userrating */
            userRating?: number | null;
        };
        /** ReactionTicketDetail */
        ReactionTicketDetail: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "adverse_reaction";
            /** Symptomdescription */
            symptomDescription: string;
            /**
             * Affectedarea
             * @default
             */
            affectedArea: string;
            /**
             * Onsetinterval
             * @default
             */
            onsetInterval: string;
            /**
             * Productbatchno
             * @default
             */
            productBatchNo: string;
            /**
             * Stoppeduse
             * @default unknown
             * @enum {string}
             */
            stoppedUse: "yes" | "no" | "unknown";
            /**
             * Soughtmedicalcare
             * @default unknown
             * @enum {string}
             */
            soughtMedicalCare: "yes" | "no" | "unknown";
        };
        /** ReceptionItemView */
        ReceptionItemView: {
            /** Conversationid */
            conversationId: string;
            /** Buyeralias */
            buyerAlias: string;
            /** Title */
            title: string;
            /** Preview */
            preview: string;
            /** Updatedat */
            updatedAt: string;
            /** Datasource */
            dataSource: string;
            /** Messagerevision */
            messageRevision: number;
            /** Unreadcount */
            unreadCount: number;
            /** Risklevel */
            riskLevel?: string | null;
            currentEmotion?: components["schemas"]["EmotionLevel"] | null;
            /** Activerisktypes */
            activeRiskTypes?: components["schemas"]["ServiceRiskType"][];
            /** Reviewrisktypes */
            reviewRiskTypes?: components["schemas"]["ServiceRiskType"][];
            /** @default operator_assisted */
            serviceMode: components["schemas"]["ServiceMode"];
            /**
             * Moderevision
             * @default 0
             */
            modeRevision: number;
            /**
             * Autoreplystatus
             * @default idle
             */
            autoReplyStatus: string;
            /** Handoffreason */
            handoffReason?: string | null;
        };
        /** ReceptionSnapshotView */
        ReceptionSnapshotView: {
            /** Items */
            items: components["schemas"]["ReceptionItemView"][];
            /** Unreadtotal */
            unreadTotal: number;
        };
        /** ReceptionStatsView */
        ReceptionStatsView: {
            /** Liveconversations */
            liveConversations: number;
            /** Historicalconversations */
            historicalConversations: number;
            /** Unreadmessages */
            unreadMessages: number;
            /** Opentickets */
            openTickets: number;
            /** Pendingrisks */
            pendingRisks: number;
        };
        /** ReplyEmpathyDimension */
        ReplyEmpathyDimension: {
            /**
             * Key
             * @enum {string}
             */
            key: "emotion_response" | "business_handling" | "personalized";
            /** Label */
            label: string;
            /**
             * Status
             * @enum {string}
             */
            status: "present" | "missing";
            /** Reason */
            reason: string;
        };
        /**
         * RequestStatus
         * @description 申请状态。不包含任何人工超时状态。
         * @enum {string}
         */
        RequestStatus: "draft" | "pending_confirmation" | "approved" | "rejected" | "needs_information";
        /**
         * RequestType
         * @description 售后申请类型。本期只生成草稿，不执行真实业务动作。
         * @enum {string}
         */
        RequestType: "refund" | "replacement" | "repair" | "parts_reshipment" | "warranty_verification" | "dealer_authorization_review" | "other";
        /** RequestView */
        RequestView: {
            /** Requestid */
            requestId: string;
            requestType: components["schemas"]["RequestType"];
            requestStatus: components["schemas"]["RequestStatus"];
            /** Requestrevision */
            requestRevision: number;
            /** Payloadhash */
            payloadHash: string;
            /**
             * Summary
             * @default
             */
            summary: string;
            /** Reviewerrole */
            reviewerRole?: string | null;
            /** Reviewedat */
            reviewedAt?: string | null;
            /** Reviewaction */
            reviewAction?: string | null;
            /** Reviewreason */
            reviewReason?: string | null;
            /** Createdat */
            createdAt: string;
        };
        /** ReshipTicketDetail */
        ReshipTicketDetail: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "reship_exchange";
            /**
             * Resolution
             * @default reship
             * @enum {string}
             */
            resolution: "reship" | "exchange";
            /** Reason */
            reason: string;
            /**
             * Productname
             * @default
             */
            productName: string;
            /**
             * Sku
             * @default
             */
            sku: string;
            /**
             * Quantity
             * @default 1
             */
            quantity: number;
        };
        /**
         * RetrievalEvidence
         * @description 检索证据契约（工程规范第 12.2 节「检索证据」一行）。
         */
        RetrievalEvidence: {
            /** Retrieval Id */
            retrieval_id: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Chunk Id */
            chunk_id: string;
            /** Document Id */
            document_id: string;
            /** Document Version */
            document_version: string;
            /** Document Title */
            document_title: string;
            /** Knowledge Base Id */
            knowledge_base_id: string;
            visibility: components["schemas"]["Visibility"];
            /** Heading Path */
            heading_path: string;
            /** Source Locator */
            source_locator: string;
            /** Quoted Excerpt */
            quoted_excerpt: string;
            /** Applicability */
            applicability: {
                [key: string]: string[] | string;
            };
            /** Channel Ranks */
            channel_ranks: {
                [key: string]: number | null;
            };
            /** Rrf Score */
            rrf_score: number;
            /** Rerank Score */
            rerank_score?: number | null;
            /** Rerank Model */
            rerank_model?: string | null;
            document_metadata?: components["schemas"]["DocumentMetadata"];
        };
        /** ReturnTicketDetail */
        ReturnTicketDetail: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "return_refund";
            /**
             * Requesttype
             * @default return_refund
             * @enum {string}
             */
            requestType: "return_refund" | "refund_only";
            /** Returnreason */
            returnReason: string;
            /**
             * Parceltype
             * @default unknown
             * @enum {string}
             */
            parcelType: "original" | "reship" | "unknown";
        };
        /**
         * ReviewRequest
         * @description 人工确认。批准绑定申请内容版本；拒绝/退回必须给原因。
         */
        ReviewRequest: {
            /** Action */
            action: string;
            /** Reason */
            reason?: string | null;
            /** Reasontext */
            reasonText?: string | null;
            /** Expectedrevision */
            expectedRevision?: number | null;
            /** Expectedpayloadhash */
            expectedPayloadHash?: string | null;
        };
        /** RiskAlertDetailView */
        RiskAlertDetailView: {
            alert: components["schemas"]["RiskAlertView"];
            serviceContext: components["schemas"]["ConsumerServiceContextView"];
        };
        /** RiskAlertStatusRequest */
        RiskAlertStatusRequest: {
            status: components["schemas"]["ServiceRiskStatus"];
            /**
             * Note
             * @default
             */
            note: string;
        };
        /** RiskAlertView */
        RiskAlertView: {
            /** Alertid */
            alertId: string;
            /** Conversationid */
            conversationId: string;
            /** Buyeralias */
            buyerAlias: string;
            /** Orderid */
            orderId?: string | null;
            /** Workorderid */
            workOrderId?: string | null;
            riskType: components["schemas"]["ServiceRiskType"];
            riskLevel: components["schemas"]["ServiceRiskLevel"];
            riskStatus: components["schemas"]["ServiceRiskStatus"];
            /** Triggersummary */
            triggerSummary: string;
            /** Evidencerefs */
            evidenceRefs: string[];
            /** Recommendedaction */
            recommendedAction: string;
            /** Createdat */
            createdAt: string;
            /** Updatedat */
            updatedAt: string;
            /** Handledby */
            handledBy?: string | null;
            /** Handledat */
            handledAt?: string | null;
            /** Handlednote */
            handledNote?: string | null;
            /**
             * Episode
             * @default 1
             */
            episode: number;
            /**
             * Revision
             * @default 1
             */
            revision: number;
            /**
             * Ruleversion
             * @default legacy
             */
            ruleVersion: string;
            /**
             * Signalactive
             * @default true
             */
            signalActive: boolean;
            /** Currentattention */
            currentAttention?: ("active" | "review" | "closed" | "historical") | null;
            /** Lastsignalat */
            lastSignalAt?: string | null;
            /** Orderids */
            orderIds?: string[];
            /** Workorderids */
            workOrderIds?: string[];
            /** Conditions */
            conditions?: {
                [key: string]: unknown;
            };
        };
        /** RiskEmotionComparisonView */
        RiskEmotionComparisonView: {
            /** Conversationid */
            conversationId: string;
            /** Points */
            points?: components["schemas"]["RiskEmotionView"][];
        };
        /** RiskEmotionView */
        RiskEmotionView: {
            /** Messageid */
            messageId: string;
            /** Conversationid */
            conversationId: string;
            /** Occurredat */
            occurredAt: string;
            /** Body */
            body: string;
            /**
             * Emotion
             * @enum {string}
             */
            emotion: "calm" | "dissatisfied" | "angry";
            /** Triggerfactors */
            triggerFactors?: string[];
        };
        /** RiskEpisodeView */
        RiskEpisodeView: {
            /** Alertid */
            alertId: string;
            /** Episode */
            episode: number;
            /** Risktype */
            riskType: string;
            /** Risklevel */
            riskLevel: string;
            /** Status */
            status: string;
            /** Closedat */
            closedAt: string;
            /** Handledby */
            handledBy?: string | null;
            /** Handlednote */
            handledNote?: string | null;
            /** Evidence */
            evidence: components["schemas"]["RiskEvidenceView"][];
            /** Ruleversion */
            ruleVersion: string;
        };
        /** RiskEvidenceView */
        RiskEvidenceView: {
            /** Ref */
            ref: string;
            /** Kind */
            kind: string;
            /** Label */
            label: string;
            /** Body */
            body: string;
            /** Occurredat */
            occurredAt?: string | null;
            /** Conversationid */
            conversationId?: string | null;
        };
        /** RiskIncidentDetailView */
        RiskIncidentDetailView: {
            incident: components["schemas"]["RiskIncidentView"];
            /** Contexts */
            contexts: components["schemas"]["ConsumerServiceContextView"][];
            /** Evidence */
            evidence: components["schemas"]["RiskEvidenceView"][];
            /** Tickets */
            tickets: components["schemas"]["TicketView"][];
            /** Handlinghistory */
            handlingHistory: components["schemas"]["TicketEventView"][];
            /** Episodes */
            episodes?: components["schemas"]["RiskEpisodeView"][];
            /** Servicebreakpointassessments */
            serviceBreakpointAssessments?: components["schemas"]["ServiceBreakpointAssessmentView"][];
            /** Judgmenthistory */
            judgmentHistory?: components["schemas"]["RiskJudgmentView"][];
            /** Contacthistory */
            contactHistory?: components["schemas"]["RiskEvidenceView"][];
            /** Emotionhistory */
            emotionHistory?: components["schemas"]["RiskEmotionView"][];
            /** Servicepoints */
            servicePoints?: components["schemas"]["RiskServicePointView"][];
            /** Emotioncomparisons */
            emotionComparisons?: components["schemas"]["RiskEmotionComparisonView"][];
        };
        /** RiskIncidentStatusRequest */
        RiskIncidentStatusRequest: {
            /**
             * Status
             * @enum {string}
             */
            status: "in_progress" | "resolved" | "ignored" | "reopen";
            /** Note */
            note: string;
            /** Expectedversion */
            expectedVersion: string;
        };
        /** RiskIncidentView */
        RiskIncidentView: {
            /** Incidentid */
            incidentId: string;
            /** Buyeralias */
            buyerAlias: string;
            /** Conversationids */
            conversationIds: string[];
            /** Primaryconversationid */
            primaryConversationId?: string | null;
            /** Orderids */
            orderIds: string[];
            /** Workorderids */
            workOrderIds: string[];
            /** Risklevel */
            riskLevel: string;
            /** Riskstatus */
            riskStatus: string;
            /** Signals */
            signals: components["schemas"]["RiskAlertView"][];
            /** Latestmessage */
            latestMessage: string;
            /** Updatedat */
            updatedAt: string;
            /** Recommendedaction */
            recommendedAction: string;
            /** Openticketcount */
            openTicketCount: number;
            /** Needsreview */
            needsReview: boolean;
            /**
             * Recurrencecount
             * @default 0
             */
            recurrenceCount: number;
            /**
             * Historicalsensitivity
             * @default 0
             */
            historicalSensitivity: number;
            /**
             * Signalactive
             * @default true
             */
            signalActive: boolean;
            /**
             * Version
             * @default
             */
            version: string;
            /** Judgments */
            judgments?: components["schemas"]["RiskJudgmentView"][];
            /** Triagescore */
            triageScore: number;
            /**
             * Triagelabel
             * @enum {string}
             */
            triageLabel: "urgent" | "priority" | "review" | "normal";
            /** Triagereasons */
            triageReasons?: string[];
            /**
             * Attentionstate
             * @enum {string}
             */
            attentionState: "active" | "review" | "closed";
            /**
             * Currentemotion
             * @enum {string}
             */
            currentEmotion: "calm" | "dissatisfied" | "angry" | "unknown";
            /**
             * Emotiontrend
             * @default unknown
             * @enum {string}
             */
            emotionTrend: "stable" | "rising" | "falling" | "repeated" | "unknown";
            /**
             * Servicestate
             * @default historical
             * @enum {string}
             */
            serviceState: "live" | "closed" | "historical";
            /** Serviceclosedat */
            serviceClosedAt?: string | null;
            /** Latestcustomerat */
            latestCustomerAt?: string | null;
            /**
             * Currentaction
             * @default none
             * @enum {string}
             */
            currentAction: "intervene" | "review" | "record_only" | "none";
        };
        /** RiskInterventionRequest */
        RiskInterventionRequest: {
            /** Conversationid */
            conversationId: string;
            /** Expectedversion */
            expectedVersion: string;
        };
        /** RiskJudgmentExportView */
        RiskJudgmentExportView: {
            /**
             * Formatversion
             * @default loreal-risk-judgments-v1
             * @constant
             */
            formatVersion: "loreal-risk-judgments-v1";
            /** Generatedat */
            generatedAt: string;
            /** Batchid */
            batchId: string | null;
            /**
             * Annotationscope
             * @default demo_operator
             * @constant
             */
            annotationScope: "demo_operator";
            /**
             * Samplingscope
             * @default detected_signals_only
             * @constant
             */
            samplingScope: "detected_signals_only";
            /**
             * Independentlyvalidated
             * @default false
             * @constant
             */
            independentlyValidated: false;
            /** Judgments */
            judgments: components["schemas"]["RiskJudgmentView"][];
        };
        /** RiskJudgmentRequest */
        RiskJudgmentRequest: {
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "confirmed" | "false_positive" | "insufficient";
            /** Note */
            note: string;
            /** Expectedversion */
            expectedVersion: string;
            /** Expectedjudgmentid */
            expectedJudgmentId?: string | null;
        };
        /** RiskJudgmentView */
        RiskJudgmentView: {
            /** Judgmentid */
            judgmentId: string;
            /** Alertid */
            alertId: string;
            /** Episode */
            episode: number;
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "confirmed" | "false_positive" | "insufficient";
            /** Actor */
            actor: string;
            /** Note */
            note: string;
            /** Detectionhash */
            detectionHash: string;
            /** Createdat */
            createdAt: string;
            /** Stale */
            stale: boolean;
            /** Supersedesid */
            supersedesId?: string | null;
            /** Risktype */
            riskType: string;
            /** Risklevel */
            riskLevel: string;
            /** Ruleversion */
            ruleVersion: string;
            /** Triggersummary */
            triggerSummary: string;
            /** Conversationid */
            conversationId: string;
            /** Orderids */
            orderIds: string[];
            /** Workorderids */
            workOrderIds: string[];
            /** Evidencerefs */
            evidenceRefs: string[];
            /** Conditions */
            conditions: {
                [key: string]: unknown;
            };
            /** Signalactive */
            signalActive: boolean;
            /** Evidence */
            evidence?: components["schemas"]["RiskEvidenceView"][];
        };
        /** RiskScanView */
        RiskScanView: {
            /** Alertscreated */
            alertsCreated: number;
            /** Incidentcount */
            incidentCount: number;
            /** Referencetime */
            referenceTime?: string | null;
        };
        /** RiskServicePointView */
        RiskServicePointView: {
            /** Messageid */
            messageId: string;
            /** Conversationid */
            conversationId: string;
            /** Occurredat */
            occurredAt: string;
            /** Body */
            body: string;
            /**
             * Senderrole
             * @enum {string}
             */
            senderRole: "operator" | "assistant";
        };
        /** SaveModelConfigRequest */
        SaveModelConfigRequest: {
            /** Baseurl */
            baseUrl?: string | null;
            /** Apikey */
            apiKey?: string | null;
            /** Model */
            model?: string | null;
            /** Visionmodel */
            visionModel?: string | null;
            /** Embeddingbackend */
            embeddingBackend?: string | null;
            /** Embeddingmodel */
            embeddingModel?: string | null;
            /** Embeddingpath */
            embeddingPath?: string | null;
            /** Embeddingbaseurl */
            embeddingBaseUrl?: string | null;
            /** Embeddingapikey */
            embeddingApiKey?: string | null;
            /** Embeddingdimension */
            embeddingDimension?: number | null;
            /** Rerankbackend */
            rerankBackend?: string | null;
            /** Rerankbaseurl */
            rerankBaseUrl?: string | null;
            /** Rerankapikey */
            rerankApiKey?: string | null;
            /** Rerankmodel */
            rerankModel?: string | null;
        };
        /** SaveModelConfigView */
        SaveModelConfigView: {
            /** Ok */
            ok: boolean;
            /** Message */
            message: string;
            config: components["schemas"]["ModelConfigView"];
        };
        /** SeenRequest */
        SeenRequest: {
            /** Revision */
            revision: number;
        };
        /** SendMessageRequest */
        SendMessageRequest: {
            /**
             * Body
             * @default
             */
            body: string;
            /** Clientmessagekey */
            clientMessageKey: string;
            /** Attachmentids */
            attachmentIds?: string[];
        };
        /** SendMessageResponse */
        SendMessageResponse: {
            message: components["schemas"]["MessageView"];
            /** Created */
            created: boolean;
            reply?: components["schemas"]["MessageView"] | null;
            decision?: components["schemas"]["AgentDecisionView"] | null;
        };
        /**
         * SenderRole
         * @description 消息发送者。渲染方向由 viewRole 计算，数据本身不翻转。
         * @enum {string}
         */
        SenderRole: "customer" | "assistant" | "operator" | "system";
        /** ServiceBreakpointAssessmentView */
        ServiceBreakpointAssessmentView: {
            /** Conversationid */
            conversationId: string;
            /** Assessmentid */
            assessmentId?: string | null;
            /**
             * Analyzed
             * @default false
             */
            analyzed: boolean;
            /**
             * Stale
             * @default false
             */
            stale: boolean;
            /**
             * Revision
             * @default 0
             */
            revision: number;
            /** Findings */
            findings?: components["schemas"]["ServiceBreakpointView"][];
            /** Modelid */
            modelId?: string | null;
            /**
             * Ismock
             * @default false
             */
            isMock: boolean;
            /** Updatedat */
            updatedAt?: string | null;
            /** Workflowsteps */
            workflowSteps?: components["schemas"]["WorkflowStep"][];
            /** Modelusage */
            modelUsage?: {
                [key: string]: unknown;
            };
        };
        /** ServiceBreakpointView */
        ServiceBreakpointView: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "repeated_question" | "unmet_promise" | "resolution_mismatch";
            /** Kindlabel */
            kindLabel: string;
            /** Topic */
            topic: string;
            /** Reason */
            reason: string;
            /** Evidence */
            evidence: components["schemas"]["BreakpointEvidence"][];
            /** Orderid */
            orderId?: string | null;
            /** Workorderid */
            workOrderId?: string | null;
            /** Detectedat */
            detectedAt: string;
            /** Promisedueat */
            promiseDueAt?: string | null;
            /** Recommendedaction */
            recommendedAction: string;
        };
        /** ServiceMemoryView */
        ServiceMemoryView: {
            /** Conversationid */
            conversationId: string;
            /**
             * Revision
             * @default 0
             */
            revision: number;
            /**
             * Stale
             * @default false
             */
            stale: boolean;
            /** Items */
            items?: components["schemas"]["MemoryItem"][];
            /** Sources */
            sources?: components["schemas"]["GroundingSource"][];
            /** Updatedat */
            updatedAt?: string | null;
            /**
             * Verified
             * @default false
             */
            verified: boolean;
        };
        /** ServiceMessageView */
        ServiceMessageView: {
            /** Sourcerecordid */
            sourceRecordId: string;
            /** Messageid */
            messageId: string;
            /** Conversationid */
            conversationId: string;
            /** Senderrole */
            senderRole: string;
            /** Sender */
            sender?: string | null;
            /** Body */
            body?: string | null;
            /** Contenttype */
            contentType: string;
            /** Imageref */
            imageRef?: string | null;
            /** Orderid */
            orderId?: string | null;
            /** Workorderid */
            workOrderId?: string | null;
        };
        /**
         * ServiceMode
         * @description 会话服务模式，与页面视角无关。
         * @enum {string}
         */
        ServiceMode: "autonomous" | "operator_assisted";
        /** ServiceModeRequest */
        ServiceModeRequest: {
            mode: components["schemas"]["ServiceMode"];
        };
        /** ServiceModeView */
        ServiceModeView: {
            /** Conversationid */
            conversationId: string;
            serviceMode: components["schemas"]["ServiceMode"];
            /** Moderevision */
            modeRevision: number;
        };
        /** ServiceNodeView */
        ServiceNodeView: {
            /** Occurredat */
            occurredAt: string;
            /** Kind */
            kind: string;
            /** Title */
            title: string;
            /** Status */
            status?: string | null;
            /** Sourcerecordid */
            sourceRecordId: string;
        };
        /** ServiceOrderView */
        ServiceOrderView: {
            /** Sourcerecordid */
            sourceRecordId: string;
            /** Orderid */
            orderId: string;
            /** Conversationid */
            conversationId: string;
            /** Buyeralias */
            buyerAlias: string;
            /** Sku */
            sku?: string | null;
            /** Productname */
            productName?: string | null;
            /** Quantity */
            quantity?: number | null;
            /** Unitpriceminor */
            unitPriceMinor?: number | null;
            /** Paidamountminor */
            paidAmountMinor?: number | null;
            /** Currency */
            currency: string;
            /** Sourcestatus */
            sourceStatus?: string | null;
            /** Orderedat */
            orderedAt: string;
            /** Paidat */
            paidAt?: string | null;
            /** Shippedat */
            shippedAt?: string | null;
            /** Carrier */
            carrier?: string | null;
            /** Trackingno */
            trackingNo?: string | null;
            /** Province */
            province?: string | null;
            /** City */
            city?: string | null;
            /** Gift */
            gift?: string | null;
            /** Buyernote */
            buyerNote?: string | null;
        };
        /** ServiceProductView */
        ServiceProductView: {
            /** Sku */
            sku?: string | null;
            /** Name */
            name: string;
            /** Unitpriceminor */
            unitPriceMinor?: number | null;
            /** Sourcerecordids */
            sourceRecordIds: string[];
        };
        /**
         * ServiceRiskLevel
         * @description 消费者服务风险等级。
         * @enum {string}
         */
        ServiceRiskLevel: "low" | "medium" | "high" | "unknown";
        /**
         * ServiceRiskStatus
         * @description 消费者服务风险处理状态。
         * @enum {string}
         */
        ServiceRiskStatus: "pending" | "in_progress" | "resolved" | "ignored";
        /**
         * ServiceRiskType
         * @description 消费者服务风险类型。
         * @enum {string}
         */
        ServiceRiskType: "emotion_escalation" | "repeated_contact" | "repeated_refund" | "adverse_reaction" | "abnormal_return" | "work_order_overdue" | "complaint_risk" | "data_conflict" | "service_breakpoint" | "response_wait" | "followup_due_soon" | "unknown";
        /** ServiceTimelineEventView */
        ServiceTimelineEventView: {
            /** Eventid */
            eventId: string;
            /** Sourcerecordid */
            sourceRecordId: string;
            /** Entitytype */
            entityType: string;
            /** Eventtype */
            eventType: string;
            /** Occurredat */
            occurredAt: string;
            message?: components["schemas"]["ServiceMessageView"] | null;
            order?: components["schemas"]["ServiceOrderView"] | null;
            workOrder?: components["schemas"]["ServiceWorkOrderView"] | null;
        };
        /** ServiceWorkOrderView */
        ServiceWorkOrderView: {
            /** Sourcerecordid */
            sourceRecordId: string;
            /** Workorderid */
            workOrderId: string;
            /** Workordertype */
            workOrderType: string;
            /** Conversationid */
            conversationId: string;
            /** Buyeralias */
            buyerAlias: string;
            /** Orderid */
            orderId?: string | null;
            /** Sourcestatus */
            sourceStatus: string;
            /** Normalizedstatus */
            normalizedStatus: string;
            /** Handler */
            handler?: string | null;
            /** Createdat */
            createdAt: string;
            /** Completedat */
            completedAt?: string | null;
            /** Detail */
            detail: {
                [key: string]: unknown;
            };
        };
        /**
         * SuggestionActionRequest
         * @description 采用或忽略候选。**采用只写草稿，不发送**。
         */
        SuggestionActionRequest: {
            /** Variant */
            variant: string;
            /** Action */
            action: string;
        };
        /** SuggestionSetView */
        SuggestionSetView: {
            /** Conversationid */
            conversationId: string;
            /** Messagerevision */
            messageRevision: number;
            /** Currentrevision */
            currentRevision: number;
            /** Expires */
            expires: boolean;
            /** Ismock */
            isMock: boolean;
            /** Modelid */
            modelId: string;
            /** Items */
            items?: components["schemas"]["SuggestionView"][];
        };
        /** SuggestionView */
        SuggestionView: {
            /** Suggestionid */
            suggestionId: string;
            /** Conversationid */
            conversationId: string;
            /** Messagerevision */
            messageRevision: number;
            /** Variant */
            variant: string;
            /** Variantlabel */
            variantLabel: string;
            /** Body */
            body: string;
            /** Ismock */
            isMock: boolean;
            /**
             * Expires
             * @default false
             */
            expires: boolean;
        };
        /** SwitchModelRequest */
        SwitchModelRequest: {
            /** Model */
            model: string;
        };
        /** SwitchModelView */
        SwitchModelView: {
            /** Model */
            model: string;
            /** Persisted */
            persisted: boolean;
            /** Message */
            message: string;
        };
        /** TestModelRequest */
        TestModelRequest: {
            /** Model */
            model: string;
        };
        /** TestModelView */
        TestModelView: {
            /** Model */
            model: string;
            /** Ok */
            ok: boolean;
            /** Latencyseconds */
            latencySeconds: number;
            /** Message */
            message: string;
        };
        /** TestRerankView */
        TestRerankView: {
            /** Model */
            model: string;
            /** Ok */
            ok: boolean;
            /** Latencyseconds */
            latencySeconds: number;
            /** Message */
            message: string;
            /** Ranked */
            ranked?: string[];
        };
        /** TicketCreateRequest */
        TicketCreateRequest: {
            /** Title */
            title: string;
            /** Conversationid */
            conversationId: string;
            /** Orderid */
            orderId?: string | null;
            /**
             * Workordertype
             * @enum {string}
             */
            workOrderType: "reship_exchange" | "offline_payment" | "logistics" | "adverse_reaction" | "return_refund";
            /**
             * Priority
             * @default normal
             * @enum {string}
             */
            priority: "low" | "normal" | "high" | "urgent";
            /**
             * Assignee
             * @default
             */
            assignee: string;
            /** Dueat */
            dueAt?: string | null;
            /** Note */
            note: string;
            /** Localdetail */
            localDetail?: (components["schemas"]["ReshipTicketDetail"] | components["schemas"]["PaymentTicketDetail-Input"] | components["schemas"]["LogisticsTicketDetail"] | components["schemas"]["ReactionTicketDetail"] | components["schemas"]["ReturnTicketDetail"]) | null;
        };
        /** TicketEventView */
        TicketEventView: {
            /** Eventid */
            eventId: string;
            /** Actor */
            actor: string;
            /** Action */
            action: string;
            /** Note */
            note: string;
            /** Createdat */
            createdAt: string;
        };
        /** TicketUpdateRequest */
        TicketUpdateRequest: {
            /** Expectedrevision */
            expectedRevision: number;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "in_progress" | "waiting_customer" | "waiting_internal" | "resolved";
            /**
             * Priority
             * @enum {string}
             */
            priority: "low" | "normal" | "high" | "urgent";
            /** Assignee */
            assignee: string;
            /** Dueat */
            dueAt?: string | null;
            /** Note */
            note: string;
            /** Localdetail */
            localDetail?: (components["schemas"]["ReshipTicketDetail"] | components["schemas"]["PaymentTicketDetail-Input"] | components["schemas"]["LogisticsTicketDetail"] | components["schemas"]["ReactionTicketDetail"] | components["schemas"]["ReturnTicketDetail"]) | null;
        };
        /** TicketView */
        TicketView: {
            /** Ticketid */
            ticketId: string;
            /** Title */
            title: string;
            /** Conversationid */
            conversationId: string;
            /** Buyeralias */
            buyerAlias: string;
            /** Orderid */
            orderId?: string | null;
            /**
             * Workordertype
             * @enum {string}
             */
            workOrderType: "reship_exchange" | "offline_payment" | "logistics" | "adverse_reaction" | "return_refund";
            /** Sourcestatus */
            sourceStatus?: string | null;
            /** Sourcerecordid */
            sourceRecordId?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "in_progress" | "waiting_customer" | "waiting_internal" | "resolved";
            /**
             * Priority
             * @enum {string}
             */
            priority: "low" | "normal" | "high" | "urgent";
            /** Assignee */
            assignee: string;
            /** Dueat */
            dueAt?: string | null;
            /** Createdat */
            createdAt: string;
            /** Updatedat */
            updatedAt: string;
            /** Revision */
            revision: number;
            /** Detail */
            detail?: {
                [key: string]: unknown;
            };
            /** Localdetail */
            localDetail?: (components["schemas"]["ReshipTicketDetail"] | components["schemas"]["PaymentTicketDetail-Output"] | components["schemas"]["LogisticsTicketDetail"] | components["schemas"]["ReactionTicketDetail"] | components["schemas"]["ReturnTicketDetail"]) | null;
            /** Events */
            events?: components["schemas"]["TicketEventView"][];
        };
        /** UpdatePromptRequest */
        UpdatePromptRequest: {
            /** Name */
            name?: string | null;
            /** Scenario */
            scenario?: string | null;
            /** Content */
            content?: string | null;
            /** Expectedrevision */
            expectedRevision?: number | null;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * Visibility
         * @description 知识可见范围。客户接口只能返回 customer_visible。
         * @enum {string}
         */
        Visibility: "customer_visible" | "internal";
        /**
         * VisionAvailabilityView
         * @description 图片能力的真实状态。未配置多模态时如实报告，不假装看懂图片。
         */
        VisionAvailabilityView: {
            /** Visionconfigured */
            visionConfigured: boolean;
            /** Maxbytes */
            maxBytes: number;
            /** Allowedmimetypes */
            allowedMimeTypes: string[];
            /** Note */
            note: string;
        };
        /** WorkOrderItem */
        WorkOrderItem: {
            /**
             * Workorderno
             * @default
             */
            workOrderNo: string;
            /** Conversationid */
            conversationId: string;
            /** Caseid */
            caseId?: string | null;
            /** Title */
            title: string;
            /**
             * Customerid
             * @default
             */
            customerId: string;
            /**
             * Category
             * @default
             */
            category: string;
            /**
             * Priority
             * @default 低
             */
            priority: string;
            /** Casestatus */
            caseStatus?: string | null;
            /** Servicemode */
            serviceMode?: string | null;
            /** Emotionlevel */
            emotionLevel?: string | null;
            /** Complaintrisk */
            complaintRisk?: string | null;
            /**
             * Pendingrequestcount
             * @default 0
             */
            pendingRequestCount: number;
            /**
             * Messagecount
             * @default 0
             */
            messageCount: number;
            /** Updatedat */
            updatedAt: string;
        };
        /** WorkOrderView */
        WorkOrderView: {
            /** Total */
            total: number;
            /** Bystatus */
            byStatus?: {
                [key: string]: number;
            };
            /** Items */
            items?: components["schemas"]["WorkOrderItem"][];
        };
        /** WorkflowStep */
        WorkflowStep: {
            /** Name */
            name: string;
            /** Status */
            status: string;
            /** Durationms */
            durationMs: number;
            /**
             * Attempt
             * @default 1
             */
            attempt: number;
            /** Issues */
            issues?: string[];
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    probe_api_health_probe_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    enums_api_contracts_enums_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: {
                            [key: string]: string;
                        };
                    };
                };
            };
        };
    };
    manifest_api_contracts_manifest_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_conversations_api_customer_conversations_get: {
        parameters: {
            query?: {
                customer_id?: string;
            };
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversationSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_conversation_api_customer_conversations_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateConversationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversationSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onboarding_api_customer_onboarding_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_messages_api_customer_conversations__conversation_id__messages_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MessageView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    send_message_api_customer_conversations__conversation_id__messages_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SendMessageRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SendMessageResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    request_handoff_api_customer_conversations__conversation_id__handoff_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceModeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_rating_api_customer_conversations__conversation_id__rating_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RatingView"] | null;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_rating_api_customer_conversations__conversation_id__rating_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RatingRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RatingView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    vision_availability_api_customer_vision_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VisionAvailabilityView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    attachment_content_api_customer_attachments__attachment_id__content_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                attachment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_attachment_api_customer_conversations__conversation_id__attachments_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_attachment_api_customer_conversations__conversation_id__attachments_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachmentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_conversation_api_customer_conversations__conversation_id__delete: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    queue_api_support_queue_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    service_queue_api_support_service_queue_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_messages_api_support_conversations__conversation_id__messages_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MessageView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    send_operator_message_api_support_conversations__conversation_id__messages_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SendMessageRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MessageView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    service_context_api_support_conversations__conversation_id__service_context_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConsumerServiceContextView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    consumer_service_assistant_api_support_conversations__conversation_id__assistant_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConsumerServiceAssistantView"] | null;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_risk_alerts_api_support_risk_alerts_get: {
        parameters: {
            query?: {
                risk_type?: components["schemas"]["ServiceRiskType"] | null;
                risk_level?: components["schemas"]["ServiceRiskLevel"] | null;
                risk_status?: components["schemas"]["ServiceRiskStatus"] | null;
            };
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskAlertView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_alert_detail_api_support_risk_alerts__alert_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskAlertDetailView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_risk_alert_status_api_support_risk_alerts__alert_id__status_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskAlertStatusRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskAlertView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    case_detail_api_support_conversations__conversation_id__case_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CaseView"] | null;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_service_mode_api_support_conversations__conversation_id__service_mode_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ServiceModeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceModeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    review_request_api_support_requests__request_id__review_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                request_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pending_requests_api_support_requests_pending_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RequestView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    audit_trail_api_support_audit__conversation_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    support_echo_api_support_health_echo_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_suggestions_api_support_conversations__conversation_id__suggestions_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuggestionSetView"] | null;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_suggestions_api_support_conversations__conversation_id__suggestions_generate_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuggestionSetView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    suggestion_action_api_support_conversations__conversation_id__suggestions_action_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SuggestionActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuggestionView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_conversation_support_api_support_conversations__conversation_id__delete: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    close_conversation_api_support_conversations__conversation_id__close_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["CloseConversationRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CloseConversationView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    model_config_api_platform_models_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelConfigView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_model_api_platform_models_test_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TestModelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestModelView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    test_rerank_api_platform_rerank_test_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TestRerankView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    knowledge_overview_api_platform_knowledge_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeOverviewWithBasesView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    work_orders_api_platform_work_orders_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkOrderView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    prompt_list_api_platform_prompts_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptListView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    switch_active_model_api_platform_models_active_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SwitchModelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SwitchModelView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_prompt_templates_api_platform_prompt_templates_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptTemplateView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_prompt_template_api_platform_prompt_templates_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreatePromptRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptTemplateView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_prompt_template_api_platform_prompt_templates__template_id__put: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdatePromptRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptTemplateView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_prompt_status_api_platform_prompt_templates__template_id__status_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PromptStatusRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptTemplateView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bind_prompt_api_platform_prompt_templates__template_id__binding_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PromptBindingRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptTemplateView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    prompt_revisions_api_platform_prompt_templates__template_id__revisions_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptRevisionView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_prompt_api_platform_prompt_templates__template_id__restore_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PromptRestoreRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PromptTemplateView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_model_config_api_platform_models_config_put: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SaveModelConfigRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SaveModelConfigView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    knowledge_bases_api_platform_knowledge_bases_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeBaseItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    queue_api_support_reception_queue_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReceptionSnapshotView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    messages_api_support_reception__conversation_id__messages_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MessageView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    send_api_support_reception__conversation_id__messages_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SendMessageRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MessageView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_attachment_api_support_reception__conversation_id__attachments_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_attachment_api_support_reception__conversation_id__attachments_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachmentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    seen_api_support_reception__conversation_id__seen_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeenRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_api_support_reception__conversation_id__assistant_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConsumerServiceAssistantView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    service_memory_api_support_reception__conversation_id__memory_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceMemoryView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    suggestion_action_api_support_reception__conversation_id__suggestion_action_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssistantActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    work_orders_api_support_reception_work_orders_all_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceWorkOrderView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_mode_api_support_reception__conversation_id__service_mode_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ServiceModeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceModeView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    operator_roster_api_support_desk_operators_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DemoOperatorRosterView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stats_api_support_desk_stats_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReceptionStatsView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ticket_list_api_support_desk_tickets_get: {
        parameters: {
            query?: {
                conversation_id?: string | null;
            };
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TicketView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ticket_create_api_support_desk_tickets_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
                "X-Demo-Operator"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TicketCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TicketView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ticket_detail_api_support_desk_tickets__ticket_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                ticket_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TicketView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    ticket_update_api_support_desk_tickets__ticket_id__put: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
                "X-Demo-Operator"?: string;
            };
            path: {
                ticket_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TicketUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TicketView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_list_api_support_desk_risks_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskIncidentView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    conversation_risks_api_support_desk_conversations__conversation_id__risks_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskIncidentView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_scan_api_support_desk_risks_scan_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskScanView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_judgment_export_api_support_desk_risk_judgments_export_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskJudgmentExportView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_judgment_api_support_desk_risks__incident_id__signals__alert_id__judgment_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
                "X-Demo-Operator"?: string;
            };
            path: {
                incident_id: string;
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskJudgmentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskIncidentDetailView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    breakpoint_assessment_api_support_desk_breakpoints__conversation_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceBreakpointAssessmentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    breakpoint_analyze_api_support_desk_breakpoints__conversation_id__post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
                "X-Demo-Operator"?: string;
            };
            path: {
                conversation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceBreakpointAssessmentView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_detail_api_support_desk_risks__incident_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                incident_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskIncidentDetailView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_update_api_support_desk_risks__incident_id__status_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
                "X-Demo-Operator"?: string;
            };
            path: {
                incident_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskIncidentStatusRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskIncidentDetailView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    risk_intervene_api_support_desk_risks__incident_id__intervene_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
                "X-Demo-Operator"?: string;
            };
            path: {
                incident_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskInterventionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskIncidentDetailView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    documents_api_platform_knowledge_documents_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeEditorView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_document_api_platform_knowledge_documents_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KnowledgeEditRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeEditorView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    products_api_platform_knowledge_products_get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeProductView"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_api_platform_knowledge_documents__document_id__get: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeEditorView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_document_api_platform_knowledge_documents__document_id__put: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KnowledgeEditRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeEditorView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_base_api_platform_knowledge_bases_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KnowledgeBaseCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    toggle_document_api_platform_knowledge_documents__document_id__status_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KnowledgeToggleRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeEditorView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    publish_api_platform_knowledge_publish_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgePublishView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_api_platform_knowledge_search_post: {
        parameters: {
            query?: never;
            header?: {
                "X-Demo-View-Role"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KnowledgeSearchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeSearchView"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
