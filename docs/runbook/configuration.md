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
| `ANKER_AGENT_RUN_MODE` | `live` / `mock` | `live` | `mock` 仅用于自动化测试与早期联调，不得作为验收依据 |

`mock` 与 `live` 的数据和报告必须分开。模型未接通时给出真实错误，
**不会静默回退为固定回复**。

## 2. 服务与网络

| 变量 | 默认 | 说明 |
|---|---|---|
| `ANKER_AGENT_API_HOST` | `127.0.0.1` | 默认只绑定本机回环 |
| `ANKER_AGENT_API_PORT` | `8000` | |
| `ANKER_AGENT_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 逗号分隔 |

> 本期没有生产级登录与访问控制。未经另行确认**不得发布到公网**。

## 3. 文本与多模态模型（OpenAI 兼容）

| 变量 | 说明 |
|---|---|
| `ANKER_AGENT_LLM_BASE_URL` | 兼容服务的基址，例如 `https://api.deepseek.com` |
| `ANKER_AGENT_LLM_API_KEY` | 密钥，只放后端，前端不持有 |
| `ANKER_AGENT_LLM_MODEL` | 文本模型 ID |
| `ANKER_AGENT_LLM_VISION_MODEL` | 多模态模型 ID；**为空则图片链路报告 unavailable** |
| `ANKER_AGENT_LLM_TIMEOUT_SECONDS` | 默认 60 |

行为约定：

- 三项（base_url / api_key / model）任一缺失时，`llm` 报告 `unavailable`，
  调用抛 `ProviderNotConfigured`（HTTP 503），**不返回固定回复**。
- 请求携带图片但 `VISION_MODEL` 未配置时，同样抛 `ProviderNotConfigured`，
  错误信息明确说明是多模态未配置。
- 超时抛 `ProviderTimeout`（HTTP 504）。**模型/工具超时与「人工等待」是完全分开的概念**，
  本期不设人工处理时限与超时升级。

## 4. 编码模型

| 变量 | 取值 | 默认 |
|---|---|---|
| `ANKER_AGENT_EMBEDDING_BACKEND` | `onnx-local` / `http` / `mock` | `onnx-local` |
| `ANKER_AGENT_EMBEDDING_MODEL_ID` | 模型 ID | `BAAI/bge-m3` |
| `ANKER_AGENT_EMBEDDING_MODEL_PATH` | 本地 ONNX 目录；留空则按缓存自动定位 | 空 |
| `ANKER_AGENT_EMBEDDING_HTTP_BASE_URL` | `http` 后端基址 | 空 |
| `ANKER_AGENT_EMBEDDING_DIMENSION` | `http` 后端需显式声明维度 | 空 |

约束：

- `live` + `mock` 组合会被直接拒绝（抛 `ProviderNotConfigured`），
  避免把伪向量混进真实验收。
- 不同编码模型不能共用同一向量空间；维度必须来自模型输出或显式声明，不填猜测值。
- **标准 `/embeddings` 接口只返回稠密向量**，因此 `http` 后端本身不等于混合检索；
  稀疏通道缺失时批次里的 `sparse` 为空，必须在报告中标注为单路检索。

## 5. 存储

| 变量 | 默认 |
|---|---|
| `ANKER_AGENT_DATABASE_URL` | `sqlite+pysqlite:///data/runtime/anker_agent.sqlite3` |
| `ANKER_AGENT_QDRANT_PATH` | `data/runtime/qdrant` |
| `ANKER_AGENT_RUNTIME_DIR` | `data/runtime` |

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
| `ANKER_AGENT_CHUNK_SIZE` | 600 | **Unicode 字符数**（`len(text)`），不是 token/字节/汉字数 |
| `ANKER_AGENT_CHUNK_OVERLAP` | 80 | 目标上限，不保证每块恰好 80 |
| `ANKER_AGENT_CHUNK_CONFIG_VERSION` | `chunk-600-80-v1` | 参数变更必须产生新快照 |
| `ANKER_AGENT_RETRIEVAL_TOP_K` | 8 | 每路（dense / sparse）召回数 |
| `ANKER_AGENT_RETRIEVAL_MAX_EVIDENCE` | 5 | RRF 合并去重后保留的最多有效片段 |

`600/80`、每路 8 条、最终最多 5 条是**待测起点**，不是已验证最优参数。
校准与留出集评测属于 S1（工程规范第 12.5 节）。

## 7. 附件

| 变量 | 默认 |
|---|---|
| `ANKER_AGENT_IMAGE_MAX_BYTES` | 5242880（5 MB） |
| `ANKER_AGENT_IMAGE_ALLOWED_MIME` | `image/jpeg,image/png,image/webp` |

前端限制不能替代后端校验：后端必须再次校验实际类型与可解码性，
并且只保存到 `data/runtime` 下的系统生成路径。

## 8. 契约版本

| 变量 | 默认 |
|---|---|
| `ANKER_AGENT_CONTRACT_VERSION` | `0.1.0` |
| `ANKER_AGENT_PROMPT_VERSION` | `s0-bootstrap` |

审计记录会带上这两个版本，便于复盘。
