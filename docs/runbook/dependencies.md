# 依赖与许可登记（S0）

冻结日期：2026-09-25。工作目录：`D:\作业\安克黑客松\2项目开发\code`。

本文件记录 **实际安装并验证** 的版本。锁文件：

- 后端：`services/api/uv.lock`（`uv lock`，93 个包）
- 前端：`apps/web/package-lock.json`

版本获取命令：

```powershell
# 后端直接依赖
.\services\api\.venv\Scripts\python.exe scripts\dump_versions.py
# 前端
cd apps\web; npm ls --depth=0
```

---

## 1. 运行环境

| 项 | 实测值 |
|---|---|
| Python | 3.11.14（`uv python install 3.11`） |
| Node.js | 24.14.0 |
| npm | 11.9.0 |
| uv | 0.9.21 |

工程规范 [工程默认] 为 Python 3.11、Node ≥ 22.12，实测一致，无需变更。

---

## 2. 后端直接依赖（精确版本，实测安装）

| 包 | 版本 | 用途 | 许可 |
|---|---|---|---|
| fastapi | 0.121.2 | API 框架、OpenAPI 生成 | MIT |
| uvicorn | 0.38.0 | ASGI 服务器 | BSD-3-Clause |
| pydantic | 2.12.4 | 契约与运行时校验（唯一事实来源） | MIT |
| pydantic-settings | 2.13.0 | 配置加载 | MIT |
| python-multipart | 0.0.20 | 附件上传 | Apache-2.0 |
| sqlalchemy | 2.0.44 | ORM（2.0 维护线） | MIT |
| langgraph | 1.0.4 | Agent 编排、中断与恢复 | MIT |
| langgraph-checkpoint-sqlite | 3.0.1 | 官方 SQLite checkpointer | MIT |
| qdrant-client | 1.16.1 | 本地持久化 + 稠密/稀疏 RRF | Apache-2.0 |
| onnxruntime | 1.23.2 | bge-m3 ONNX CPU 推理 | MIT |
| huggingface-hub | 0.36.0 | 模型下载 | Apache-2.0 |
| tokenizers | 0.22.1 | bge-m3 分词 | Apache-2.0 |
| numpy | 2.3.4 | 数值计算 | BSD-3-Clause |
| jieba | 0.42.1 | 中文分词（备用/工具） | MIT |
| rapidfuzz | 3.14.3 | 卖家名称模糊匹配 | MIT |
| pillow | 12.0.0 | 图片类型与可解码性校验 | MIT-CMU |
| httpx | 0.28.1 | 测试客户端 | BSD-3-Clause |
| python-dotenv | 1.2.1 | `.env` 加载 | BSD-3-Clause |

开发依赖：pytest 9.0.1、pytest-asyncio 1.3.0、pytest-cov 7.0.0、
ruff 0.14.5、mypy 1.18.2（均为 MIT/BSD 系）。

关键传递依赖：starlette 0.49.3、langchain-core 1.6.5、langgraph-checkpoint 3.0.1、
protobuf 7.36.2、pyyaml 6.0.3、tenacity 9.1.4。

---

## 3. 前端直接依赖（精确版本，实测安装）

| 包 | 版本 | 用途 |
|---|---|---|
| react | 19.3.0 | UI 框架 |
| react-dom | 19.3.0 | — |
| antd | 6.6.5 | 组件库 |
| @ant-design/x | 2.9.0 | 聊天构件（已接入 `Conversations`、`Bubble`、`Sender`、`Attachments`、`Prompts`、`Sources`，见第 3.1 节） |
| @ant-design/icons | 6.3.4 | 图标 |
| react-router-dom | 7.18.4 | 路由（左栏视角切换） |
| vite | 7.3.6 | 构建与开发服务器 |
| typescript | 5.9.3 | 类型检查 |
| vitest | 4.1.11 | 组件单元测试 |
| @playwright/test | 1.63.0 | 端到端与截图 |
| @testing-library/react | 16.3.3 | 组件测试 |
| @testing-library/jest-dom | 6.10.0 | 断言扩展 |
| @testing-library/user-event | 14.6.7 | 交互模拟 |
| jsdom | 28.1.0 | 测试 DOM 环境 |
| openapi-typescript | 7.13.0 | 由 OpenAPI 生成 TS 类型 |
| eslint | 9.39.5 | 静态检查（`npx eslint .`；配置文件 `apps/web/eslint.config.js` 为本轮补齐，此前 `npm run lint` 因缺配置直接以退出码 2 失败，见台账缺陷第 50 项） |
| typescript-eslint | 8.70.1 | TS 规则（只启用推荐集，不做类型感知检查） |
| @vitejs/plugin-react | 5.2.0 | React 插件 |
| @types/react / @types/react-dom | 19.3.0 | 类型 |
| @types/node | 24.x | 类型 |

### 3.1 版本选择说明（与工程规范的偏差）

工程规范 [工程默认] 为 React 19、TypeScript 5.9、Vite 7、Ant Design 6、Ant Design X 2。
实测时 npm 上的 `latest` 已经是 **TypeScript 7.0.2** 与 **Vite 8.3.1**，
二者都不是规范指定的主版本。S0 决定**保持在规范指定的主版本内并使用各自主版本的最新补丁**，
理由：TypeScript 7 是编译器重写、Vite 8 是新的主版本，把两者同时引入会把
「依赖兼容性未验证」的风险叠加上去，而本期没有任何需求需要它们的新能力。

`@ant-design/x@2` 的 peerDependencies 要求 `antd ^6.1.1`、`react >=18`，实测组合满足。

### 3.1 Ant Design X 实际接入情况（如实记录）

工程规范第 21 行要求「复用 Conversations、Bubble、Sender、Attachments 与表单，不重写聊天基础组件」。
当前实际接入与缺口：

| 组件 | 状态 | 说明 |
|---|---|---|
| `Conversations` | 已接入 | 会话列表主体；因它渲染的 `<li>` 不可聚焦，每项 `label` 内放一个真正的 `<button>` 保证键盘可达 |
| `Bubble` | 已接入 | 消息气泡，用 `avatar`/`header`/`footer` 槽位承载头像、角色名与时间 |
| `Sender` | 已接入 | 客户与客服两处输入区；`components.input` 注入带 `aria-label` 的输入控件 |
| `Attachments` | 已接入 | 图片上传（触发按钮 + 文件卡片 + 拖拽）；`beforeUpload` 返回 false，真实上传仍走后端校验 |
| `Prompts` | 已接入 | AI 话术候选三版纵向铺开 |
| `Sources` | 已接入 | 「知识依据」页签的来源列表 |

组件级视觉规格见 `06_前端设计/前端设计与交互规范.md` 第 7.1 节（含页面骨架、每个构件的
尺寸与颜色、四条实现约束，以及参考图里**不照做**的三处）。

**两点必须知道的实现约束**（都是实测踩出来的，不是推测）：

1. `Sender` 的默认发送按钮是纯图标、**没有可访问名**，且其实现由 `Sender.js`
   内部 `import SendButton`，**没有通过 props 暴露**（`SenderComponents` 只声明
   `input`）。`suffix` 拿到的 `components.SendButton` 只用于渲染，
   **替换它不影响提交逻辑**——用它渲染自写按钮会导致点击后消息发不出去。
   因此发送按钮由我们渲染并调用同一 `onSubmit`（见 `SenderParts.tsx`）。
2. `Conversations` 渲染的 `<li>` 没有 button 语义也不可聚焦，直接使用会让
   键盘用户无法切换会话。

工程规范第 21 行点名的四个组件（`Conversations`/`Bubble`/`Sender`/`Attachments`）**均已接入**，
并额外按要求复用了 `Prompts`（话术候选）与 `Sources`（知识依据）。
`XProvider` 未使用：本期没有多主题或多语言切换需求，引入它只增加一层无收益的包装。

视觉层（本轮补）：色板与 antd 主题令牌在 `apps/web/src/styles/theme.ts`，跨组件复用的类在
`apps/web/src/styles/global.css`（页面骨架 `.anker-shell`/`.anker-panel`、左栏、列表行、气泡、
候选面板、输入区、信息行），单组件样式就近写在组件文件里。antd `List` 已在本期改为普通映射
渲染：v6.6 起它被标记为废弃并提示改用 `Listy`，而 `Listy` 面向虚拟滚动，这里的申请列表只有
0—2 条、用不上。

发送按钮与输入控件有两处刻意的自定义（`apps/web/src/components/SenderParts.tsx`），
原因是组件库的限制，不是偏好，详见上表的两条实现约束。

---

## 4. 编码模型与稀疏通道

| 项 | 实测值 |
|---|---|
| 模型 | `BAAI/bge-m3` |
| revision（snapshot commit） | `5617a9f61b028005a4858fdac845db406aefb181` |
| 权重格式 | ONNX（`onnx/model.onnx` + `onnx/model.onnx_data`，约 2.2 GB fp32） |
| 许可 | MIT |
| 稠密维度 | 1024（从 ONNX 输出形状读取，非猜测） |
| 稀疏通道来源 | `sparse_linear.pt`（weight `(1,1024)` float16 + bias），**实测 `external_linear`** |
| 加载耗时 | 1.9—2.5 秒（首次，CPUExecutionProvider） |
| 单条查询编码 | 0.04 秒 |
| 6 条批量编码 | 2.36 秒（约 0.39 秒/条） |

### 4.1 为什么不用 torch / FlagEmbedding

bge-m3 的 ONNX 导出只包含 `token_embeddings` 与 `sentence_embedding`，
稀疏通道所需的 `sparse_linear` 权重只以 legacy（zip + pickle）`.pt` 提供，
官方 FlagEmbedding 依赖 torch 读取。本项目只需读取一个 `1x1024` 线性层，
为此引入约 2 GB 的 torch 依赖不划算，因此
`app/integrations/checkpoint_loader.py` 用标准库 `zipfile` + `pickle`
复现了 `torch.load` 的最小语义。

已验证（`scripts/probe_sparse_linear_load.py`）：
- `sparse_linear.pt` → weight `(1,1024)` float16、bias `(1,)`
- `colbert_linear.pt` → weight `(1024,1024)`、bias `(1024,)`（本期不使用 ColBERT）

### 4.2 稀疏通道的正确算法（实测修正）

必须**逐 token** 计算词项权重后再按 token id 做 max 归约：

```
token_weights = relu(token_embeddings @ sparse_weight + sparse_bias)   # (batch, seq)
按 input_ids 归约（同 id 取 max）-> 词表维度稀疏向量
```

反例（已实测排除）：先对 token 嵌入做句级 mean-pooling 再投影，每个文本
只会得到 **1 个** 标量，无法形成词项级稀疏向量。证据脚本：
`scripts/probe_sparse_diag.py`（修正前 `sparse_nonzero_counts` 全为 1，
修正后为 15—25）。

---

## 5. 安全检查结果

- 已核对：直接依赖均为 MIT / Apache-2.0 / BSD 系许可，无 GPL/AGPL 传染风险。
- 未执行：自动化漏洞扫描（`pip-audit` / `npm audit`）。**S0 未做此项，不声称通过。**
- 凭证：`.env` 已加入 `.gitignore`；日志与健康检查均不输出密钥值。
