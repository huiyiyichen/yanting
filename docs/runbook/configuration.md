# 运行配置说明

配置来源优先级（高 → 低）：

1. 真实环境变量
2. `services/api/.env`（由 `app/config.py` 读入环境，不覆盖已存在的环境变量）
3. `app/config.py` 中的默认值

模型凭证使用本机 `services/api/.env`；仓库根目录 `.env.example` 提供空凭证模板。

---

## 1. 运行模式

| 变量 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `YANTING_RUN_MODE` | `live` / `mock` | `live` | `mock` 仅用于自动化测试与早期联调，不得作为验收依据 |

`mock` 与 `live` 的数据和报告必须分开。模型未接通时给出真实错误，
**不会静默回退为固定回复**。

## 2. 服务与网络

| 变量 | 默认 | 说明 |
|---|---|---|
| `YANTING_API_HOST` | `127.0.0.1` | 默认只绑定本机回环 |
| `YANTING_API_PORT` | `8000` | |
| `YANTING_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 逗号分隔 |

> 本期没有生产级登录与访问控制。未经另行确认**不得发布到公网**。

## 3. 文本与多模态模型（OpenAI 兼容）

| 变量 | 说明 |
|---|---|
| `YANTING_LLM_BASE_URL` | 兼容服务的基址，例如 `https://api.deepseek.com` |
| `YANTING_LLM_API_KEY` | 密钥，只放后端，前端不持有 |
| `YANTING_LLM_MODEL` | 文本模型 ID |
| `YANTING_LLM_VISION_MODEL` | 多模态模型 ID；**为空则图片链路报告 unavailable** |
| `YANTING_LLM_VISION_BASE_URL` | 独立视觉服务地址，留空复用文本服务 |
| `YANTING_LLM_VISION_API_KEY` | 独立视觉凭证，留空复用文本凭证 |
| `YANTING_LLM_FAST_MODEL` | 快速模型 ID，留空复用主模型 |
| `YANTING_LLM_TIMEOUT_SECONDS` | 默认 60 |

行为约定：

- 三项（base_url / api_key / model）任一缺失时，`llm` 报告 `unavailable`，
  调用抛 `ProviderNotConfigured`（HTTP 503），**不返回固定回复**。
- 请求携带图片但 `VISION_MODEL` 未配置时，同样抛 `ProviderNotConfigured`，
  错误信息明确说明是多模态未配置。
- 超时抛 `ProviderTimeout`（HTTP 504）。**模型/工具超时与「人工等待」是完全分开的概念**，
  本期不设人工处理时限与超时升级。

### 3.1 接待与预警阈值

| 变量 | 默认 | 说明 |
|---|---|---|
| `YANTING_AUTO_REPLY_TIMEOUT_SECONDS` | `45` | AI 接待模式下等待自动回复的超时（秒），范围 5–120 |
| `YANTING_RISK_RESPONSE_WAIT_SECONDS` | `120` | 风险事件等待客服响应的时长，`0` 停用 |
| `YANTING_RISK_FOLLOWUP_WARNING_MINUTES` | `30` | 跟进未完成的预警提前量（分钟），`0` 停用 |
| `YANTING_RISK_MONITOR_INTERVAL_SECONDS` | `15` | 风险监控轮询间隔（秒），范围 5–300 |
| `YANTING_RISK_REPEAT_CONTACT_HOURS` | `72` | 重复进线的回溯窗口（小时） |
| `YANTING_VERIFY_ON_DEMAND` | `true` | 回复不含编号、金额、日期、状态、商品身份、成分功效断言，且无高风险、个性化建议、服务断点或图片时，只做程序校验，不调用模型核验；`false` 恢复每次核验 |
| `YANTING_MODEL_PRICES_JSON` | 空 | 模型价格表 JSON，键为实际响应模型 ID，值为每百万 Token 的 `input`、`cachedInput`（可选）、`output` 单价（元）。留空或模型未列出时 `/api/platform/usage` 只统计次数与 Token，不估算费用 |
| `YANTING_RISK_SOURCE_TICKET_HOURS` | `48` | 由工单触发风险的窗口（小时） |

这些是演示阈值，不代表生产 SLA。风险状态只由程序规则和客服操作改变，
模型不能把风险标记为已处理或已忽略。

## 4. 编码模型

模型请求在 DeepSeek 官方端点传 `thinking.type=disabled`，Qwen3 文本模型在硅基流动及百炼端点传 `enable_thinking=false`。Qwen3-VL-Instruct 采用直接输出；硅基流动此型号拒绝 `enable_thinking` 参数，视觉请求省略该字段。调用记录保留供应方响应中的实际型号与缓存命中 Token；视觉请求使用视觉服务自己的端点和凭证。

| 变量 | 取值 | 默认 |
|---|---|---|
| `YANTING_EMBEDDING_BACKEND` | `onnx-local` / `http` / `mock` | `onnx-local` |
| `YANTING_EMBEDDING_MODEL_ID` | 模型 ID | `BAAI/bge-m3` |
| `YANTING_EMBEDDING_MODEL_PATH` | 本地 ONNX 目录；留空则按缓存自动定位 | 空 |
| `YANTING_EMBEDDING_HTTP_BASE_URL` | `http` 后端基址 | 空 |
| `YANTING_EMBEDDING_HTTP_API_KEY` | `http` 后端凭证，只放后端 | 空 |
| `YANTING_EMBEDDING_DIMENSION` | `http` 后端需显式声明维度 | 空 |

约束：

- `live` + `mock` 组合会被直接拒绝（抛 `ProviderNotConfigured`），
  避免把伪向量混进真实验收。
- 不同编码模型不能共用同一向量空间；维度必须来自模型输出或显式声明，不填猜测值。
- **标准 `/embeddings` 接口只返回稠密向量**，因此 `http` 后端本身不等于混合检索；
  稀疏通道缺失时批次里的 `sparse` 为空，必须在报告中标注为单路检索。

### 4.1 重排模型（可选）

| 变量 | 取值 | 默认 |
|---|---|---|
| `YANTING_RERANK_BACKEND` | `none` / `http` / `mock` | `none` |
| `YANTING_RERANK_BASE_URL` | OpenAI 兼容 rerank 服务基址 | 空 |
| `YANTING_RERANK_API_KEY` | 凭证，只放后端 | 空 |
| `YANTING_RERANK_MODEL` | 重排模型 ID | 空 |
| `YANTING_RERANK_TIMEOUT_SECONDS` | 超时（秒） | `30` |
| `YANTING_RERANK_CANDIDATES` | 送入重排的候选数，范围 2–64 | `16` |

**默认是 `none`，即重排关闭**：此时候选只按稠密/稀疏融合排序。需要重排时必须显式
把 `BACKEND` 设为 `http` 并补齐地址、凭证与模型，否则不会报错、也不会生效。

## 5. 存储

| 变量 | 默认 |
|---|---|
| `YANTING_DATABASE_URL` | `sqlite+pysqlite:///data/runtime/yanting.sqlite3` |

默认库为 `data/runtime/yanting.sqlite3`；若只存在旧库 `anker_agent.sqlite3` 则继续使用旧库（不迁移、不删除）。
| `YANTING_QDRANT_PATH` | `data/runtime/qdrant` |
| `YANTING_RUNTIME_DIR` | `data/runtime` |

相对路径按**仓库根目录**解析，不受启动目录影响。运行数据不入 Git。

### 5.1 Qdrant 本地模式的实现约束

`QdrantClient(path=...)` 使用文件锁：**同一目录同时只允许一个进程写入**。
因此本期为单后端进程；导入走同一进程或停机后离线执行。需要并发时应切换到
Qdrant Server 并验证，不能用跳过文件锁的方式绕过。

另外，Qdrant 本地客户端必须**显式 `close()`**：若依赖 `__del__` 收尾，
CPython 解释器关闭阶段 portalocker 会尝试 `import msvcrt` 并失败，
打印堆栈且进程以非 0 退出。已在 Windows + Python 3.11 实测确认，
证据脚本 `scripts/_probe_qdrant_close.py`（显式 close 后退出码 0）。

## 6. 知识切片与检索

| 变量 | 默认 | 说明 |
|---|---|---|
| `YANTING_CHUNK_SIZE` | 600 | **Unicode 字符数**（`len(text)`），不是 token/字节/汉字数 |
| `YANTING_CHUNK_OVERLAP` | 80 | 目标上限，不保证每块恰好 80 |
| `YANTING_CHUNK_CONFIG_VERSION` | `chunk-600-80-v1` | 参数变更必须产生新快照 |
| `YANTING_RETRIEVAL_TOP_K` | 8 | 每路（dense / sparse）召回数 |
| `YANTING_RETRIEVAL_MAX_EVIDENCE` | 5 | RRF 合并去重后保留的最多有效片段 |

`600/80`、每路 8 条、最终最多 5 条是**待测起点**，不是已验证最优参数。
校准与留出集评测属于 S1（工程规范第 12.5 节）。

## 7. 附件

| 变量 | 默认 |
|---|---|
| `YANTING_IMAGE_MAX_BYTES` | 5242880（5 MB） |
| `YANTING_IMAGE_ALLOWED_MIME` | `image/jpeg,image/png,image/webp` |

前端限制不能替代后端校验：后端必须再次校验实际类型与可解码性，
并且只保存到 `data/runtime` 下的系统生成路径。

## 8. 契约版本

| 变量 | 默认 |
|---|---|
| `YANTING_CONTRACT_VERSION` | `0.1.0` |
| `YANTING_PROMPT_VERSION` | `s0-bootstrap` |

审计记录会带上这两个版本，便于复盘。

## 9. 模型配置端到端验收

失败场景与预期（先于后续适配实现记录）：视觉配置指向文本网关时应从请求目标识别；视觉独立凭证与文本凭证混用时请求应失败并显示该能力错误；连接检查改变并发接待模型时应保持接待模型原值；保存空密钥时保留原值；返回配置中应只含密钥掩码；模型别名与服务实际响应名应分别保留；缓存Token缺省时统计按零处理；服务地址已有`/v1`时请求路径只包含一次版本号。

复现：启动前后端，在模型配置页分别保存文本与视觉配置，重新打开抽屉核对持久化字段；通过客户页发送真实商品图片，读取对应回复与运行记录的模型名。产物记录执行时间、源码提交、实际模型、HTTP结果和脱敏截图，保存到`evals/results/`与`output/playwright/model-config/`。验收数据使用`data/runtime/validation/model-config/`。

2026-10-14 本批记录：模型配置页面实际点击文本连接检查，HTTP 200，返回`deepseek-flash`，0.772秒；视觉抽屉显示独立地址与密钥字段。截图`output/playwright/model-config/models-page.png`。供应方调用记录`evals/results/model-provider-qwen-20261014.json`包含文本/快速模型成功和首次视觉参数错误；修正后的视觉记录为`evals/results/model-provider-vision-20261014.json`，返回`Qwen/Qwen3-VL-8B-Instruct`，23.505秒，图片回答为“欧莱雅复颜气垫粉底液”。官方图片对应“黑胖子气垫200中性象牙白”，此结果证明图片请求通路，商品识别准确性与完整接待仍待后续评测。各JSON包含直接复现命令、输入图片哈希、实际响应模型及Token。
