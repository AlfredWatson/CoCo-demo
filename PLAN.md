# 机密计算前期 Demo 分层验证行动指南

## 一、Demo 总体目标

由于当前没有真实 CC 硬件，Demo 分成三层，严格区分证据强度：

| 层级 | 当前能否完成 | 要证明什么 | 不能证明什么 |
|---|---:|---|---|
| L1：逻辑 PoC | 现在可以 | 加密模型、条件发钥、解密加载、失败拒绝、推理接口可形成闭环 | 不能证明宿主机管理员看不到内存 |
| L2：单节点真实 CC | 拿到机器后 | CVM、CPU TEE、GPU CC、真实证明和真实发钥 | 不能证明 Kubernetes 集群化 |
| L3：机密容器集群 | 项目启动后 | Kata、GPU Operator、Trustee/KBS、Kubernetes 调度和完整运维链路 | 生产安全仍需正式 KMS/HSM、审计和安全评审 |

第一阶段推荐使用一个小模型完成流程验证：

- 默认模型：`Qwen2.5-0.5B-Instruct`。
- 默认推理服务：有普通 NVIDIA GPU 时使用 vLLM；没有 GPU 时先用 Transformers/FastAPI，保持 OpenAI-compatible API。
- 默认接口：`POST /v1/chat/completions`。
- 模型目录整体打包后使用 AES-256-GCM 加密。
- 运行时只解密到内存文件系统，不在普通磁盘留下明文模型。
- 所有镜像、依赖和配置锁定版本并记录摘要。

## 二、L1：当前即可完成的逻辑 PoC

预计投入 5～7 个工作日。

### 步骤 0：定义边界和验收口径

准备环境：

- 不需要 CC 硬件。
- 准备一台 Linux x86_64 开发机，建议 Ubuntu 22.04/24.04。
- 最低 32 GB 内存、100 GB 空闲磁盘。
- 推荐有一张普通 CUDA GPU；没有也不影响安全流程验证。

完成任务：

- 固定模型、推理框架、API、测试数据和性能参数。
- 创建证据分级说明：`logic-only`、`real-cc-single-node`、`real-cc-k8s`。
- 明确第一阶段威胁模型：验证流程正确，但不假设普通宿主机可信隔离。
- 明确敏感信息清单：模型明文、模型密钥、Prompt、响应不得进入日志。

达到目标：

- 团队对“这次 Demo 能证明什么、不能证明什么”达成书面共识。
- 禁止在 L1 结论中使用“已实现硬件级机密计算”等表述。

### 步骤 1：建立普通推理基线

准备环境：

- Docker Engine、Docker Compose v2。
- `git`、`curl`、`openssl`、`jq`。
- 有 GPU时准备 NVIDIA 驱动和 NVIDIA Container Toolkit。
- 下载小模型到独立模型目录。

完成任务：

- 用固定镜像启动 vLLM 或 Transformers 服务。
- 暴露 `/health/live`、`/health/ready` 和 `/v1/chat/completions`。
- 固定测试条件：

  - 输入约 256 tokens。
  - 输出上限 128 tokens。
  - 并发分别为 1、4、8。
  - 温度固定为 0。
  - 每组至少 30 个请求。

- 记录模型哈希、镜像 digest、CUDA、驱动、推理框架和启动参数。

达到目标：

- 健康检查通过。
- Chat Completions 请求能够稳定返回。
- 形成普通环境基线：启动耗时、TTFT P50/P95、TPOT P50/P95、输出吞吐、错误率和显存占用。
- 所有后续 CC 性能对比都复用完全相同的工作负载和版本记录。

### 步骤 2：完成模型加密和安全加载

准备环境：

- OpenSSL 或等效 AES-256-GCM 工具。
- Linux `tmpfs`。
- 一个独立生成的 256-bit 数据加密密钥 DEK。
- Demo 阶段的 DEK 存放在模型服务容器之外。

完成任务：

1. 将完整模型目录打包。
2. 生成随机 DEK。
3. 使用 AES-256-GCM 加密模型包，同时保存 nonce、认证标签和密文哈希。
4. 删除 Demo 工作目录中的明文副本，但保留可重新下载的原始模型来源。
5. 模型服务启动时获取 DEK。
6. 将模型仅解密到 `tmpfs`。
7. vLLM/Transformers 从 `tmpfs` 加载模型。
8. 服务退出时卸载临时目录并确认没有明文残留。

达到目标：

- 磁盘和镜像中只能找到模型密文。
- 正确密钥可以加载模型。
- 错误密钥、密文被修改或认证标签错误时，启动失败。
- 失败状态下 `/health/live` 可以存活，但 `/health/ready` 必须失败，推理接口不得接受请求。

这一步只证明模型加密与加载逻辑；普通宿主机管理员仍可能读取容器内存或 `tmpfs`。

### 步骤 3：运行本地 Trustee 学习环境

准备环境：

- Docker Compose。
- 可访问 GitHub Container Registry。
- ORAS CLI。
- CNCF Confidential Containers 的 Trustee，包括：

  - KBS：密钥/资源请求入口。
  - AS：Attestation Service。
  - RVPS：可信参考值服务。

完成任务：

- 使用 Trustee 官方 Docker Compose 启动 KBS、AS 和 RVPS。
- 检查容器状态和 KBS `8080` 端口。
- 安装 `kbs-client`。
- 向 KBS 发起无有效硬件证据的资源请求。
- 观察 KBS、AS 和策略引擎日志。

达到目标：

- KBS、AS、RVPS 均正常运行。
- 请求能够到达策略引擎。
- 因没有真实 TEE 证据，资源请求被拒绝。

这里“拒绝”就是成功结果：它证明服务连接和默认拒绝策略工作，但不代表完成了硬件证明，也不会向工作负载释放真实秘密。[NVIDIA Trustee 本地验证说明](https://docs.nvidia.com/datacenter/cloud-native/confidential-containers/latest/attestation.html)

### 步骤 4：实现可替换的启动门禁

Demo 使用两个明确分开的证明适配器：

```text
ATTESTATION_PROVIDER=mock      # L1 逻辑演示
ATTESTATION_PROVIDER=trustee   # L2/L3 真实环境
```

准备环境：

- 一个仅供 Demo 使用的 Mock Attestation 服务。
- 单独的 Demo Key Broker，密钥不得写入模型容器镜像或环境变量。
- 本地签名密钥，用于签发不可伪造的 Demo assertion。
- 每次请求使用新的 nonce，assertion 设置短有效期。

完成任务：

- Mock assertion 至少包含：

  - 工作负载镜像 digest。
  - 模型密文 SHA-256。
  - 推理配置摘要。
  - nonce。
  - 策略版本。
  - 签发和过期时间。
  - `environment=demo-mock` 标记。

- 启动门禁执行固定流程：

```text
模型服务启动
  → 获取挑战 nonce
  → 提交证明
  → 校验签名、nonce、有效期、镜像和模型摘要
  → 校验通过才向 Key Broker 请求 DEK
  → tmpfs 内解密
  → 校验模型内容哈希
  → 启动推理服务
  → /health/ready 变为成功
```

- `trustee` 适配器保留同样的“获取密钥”业务接口，后续替换时不修改模型服务主体。

达到目标：

- 没有 assertion：不发钥。
- assertion 过期：不发钥。
- nonce 重放：不发钥。
- 镜像或模型摘要不匹配：不发钥。
- 合格 Mock assertion：发放 DEK、加载模型并提供推理。
- 日志只能记录请求 ID、策略版本、拒绝原因和组件状态，不记录密钥、Prompt、结果或模型内容。

### 步骤 5：执行失败注入和性能验证

准备环境：

- 自动化测试脚本。
- 固定 Prompt 数据集。
- 基线服务和加密启动服务使用同一模型、镜像和推理参数。

必须覆盖：

1. 正确 assertion + 正确密文：成功推理。
2. 无 assertion：拒绝发钥。
3. 过期 assertion：拒绝。
4. 重放旧 nonce：拒绝。
5. 错误镜像 digest：拒绝。
6. 模型密文被修改一个字节：AES-GCM 校验失败。
7. 错误 DEK：解密失败。
8. 推理进程崩溃重启：重新证明，不能复用旧 assertion。
9. Key Broker 不可达：服务保持 not-ready，不能绕过。
10. 检查容器镜像、挂载目录、日志和环境变量中不存在明文 DEK。
11. 普通版与加密启动版执行相同基准，分别记录启动时间与推理性能。

达到目标：

- 所有失败场景均为 fail closed。
- 加密主要增加启动阶段的解密时间；推理阶段性能差异单独报告。
- 输出原始请求结果、服务日志、版本、配置、指标和错误数，而不只提供汇总百分比。

### 步骤 6：整理可演示交付物

建议后续实现放在：

```text
research/机密计算研究/demo/
├── compose/
├── model-encryption/
├── inference/
├── mock-attestation/
├── tests/
├── benchmark/
└── README.md
```

交付物包括：

- 一键启动和停止说明。
- 模型加密与校验脚本。
- Mock assertion 和条件发钥服务。
- Trustee 本地 Compose 验证记录。
- 推理服务镜像与锁定版本。
- 成功路径和失败路径自动测试。
- 基准结果和原始日志。
- `证据边界说明.md`。
- `真实CC环境验收清单.md`。

客户演示顺序固定为：

1. 展示磁盘上只有加密模型。
2. 无证明启动，模型服务拒绝就绪。
3. 使用错误摘要，仍然拒绝。
4. 使用合格 Demo assertion，取得密钥。
5. 模型在 `tmpfs` 中加载并提供推理。
6. 明确说明当前是逻辑 PoC，下一阶段才验证硬件隔离。

## 三、L2：拿到单台真实 CC 机器后的验证

预计投入 5～10 个工作日，前提是服务器厂商已经完成 BIOS、固件和平台适配。

### 环境准备

- 使用 NVIDIA 当前支持矩阵中的确切服务器型号，而不是只确认“有 H200/B200”。
- CPU 支持并启用 Intel TDX 或 AMD SEV-SNP。
- GPU SKU 支持 NVIDIA CC。
- OEM 提供匹配的 BIOS、GPU 固件、VBIOS、Host OS、内核和驱动组合。
- 准备独立 Trustee/KBS 机器，不能与被证明的工作负载共用同一信任域。
- 先做单 GPU CVM，不在第一轮同时引入 Kubernetes。

NVIDIA 明确要求按照“服务器型号、CPU TEE、GPU SKU、固件、驱动、GPU 模式、运行时”形成一个完整的已验证配置档案，支持状态不能由单个型号推断。[NVIDIA 平台要求](https://docs.nvidia.com/enterprise-reference-architectures/deploying-proprietary-models-confidential-compute-self-hosted-kubernetes/latest/platform-and-hardware-requirements.html)

### 验证任务

1. 收集 CPU、内存、GPU、VBIOS、固件、驱动、内核和拓扑信息。
2. 验证 TDX/SEV-SNP 已启用。
3. 创建 CVM，将单张 GPU 通过 VFIO 分配给 CVM。
4. 检查 GPU CC 模式为 `ON`。
5. 在 CVM 内运行 CUDA 基础测试。
6. 完成 CPU 和 GPU 的真实 Attestation。
7. 检查 token 的 nonce、时间、设备、固件和 CC 状态等 claims。
8. 将 Mock assertion 替换为 Trustee/真实证明适配器。
9. 配置策略：只有批准的 CPU、GPU、guest、镜像、模型和策略版本可以取得 DEK。
10. 运行 L1 的全部成功、失败与性能测试。

### 达到目标

- GPU CC 为 ON，并有可留档的查询输出。
- CPU、GPU 和工作负载证明均通过。
- 修改镜像、guest、固件状态或策略后不能取得 DEK。
- 正确环境取得 DEK，模型只在 CVM 内解密。
- 普通模式与 CC 模式使用同一基准，给出 TTFT、TPOT、吞吐、错误率和启动耗时差异。
- 此时才能声明“完成单节点硬件级机密推理验证”。

## 四、L3：Kubernetes 机密容器完整 Demo

预计额外投入 1～2 周。

### 环境准备

- 至少一个经过验证的 CC GPU 工作节点。
- 独立控制节点和独立 Trustee/KBS。
- Kubernetes、containerd、Kata Containers、GPU Operator、Trustee。
- 版本以采购时 NVIDIA 支持矩阵为准，不照抄项目草稿中的固定版本。

截至当前 NVIDIA 参考架构使用 Kubernetes 1.32+、Kata Containers 3.29、GPU Operator 26.3.1+ 和 containerd 2.2.2，但这些属于时点配置，正式实施前必须再次核对。[NVIDIA Reference Implementation](https://docs.nvidia.com/enterprise-reference-architectures/deploying-proprietary-models-confidential-compute-self-hosted-kubernetes/latest/reference-implementations.html)

### 验证任务

1. 安装 Kata 和 TEE 对应 RuntimeClass。
2. 安装 GPU Operator 及 CC、VFIO、Kata 相关组件。
3. 配置 CC GPU 节点标签与调度规则。
4. 先运行 NVIDIA 官方 Sample Workload。
5. 部署 Trustee/KBS、AS、RVPS 和参考值。
6. 部署加密模型服务。
7. Pod 在机密 VM 中完成 CPU+GPU+guest+镜像联合证明。
8. 证明通过后，由 KBS 将 DEK 发入机密 guest。
9. HTTPS 在可信工作负载边界内终结。
10. 验证 Pod 重建、节点重启、策略升级和密钥轮换。
11. 验证 Kubernetes Secret、宿主机卷、日志和监控系统中没有模型 DEK、Prompt 和响应。

### 达到目标

- RuntimeClass 能创建机密 Pod。
- GPU Sample Workload 输出 `Test PASSED`。
- 机密 Pod 可以使用 GPU 推理。
- 普通 Pod、被篡改 Pod 和错误节点均无法取得模型密钥。
- K8s 管理员仍可调度、监控和重启服务，但拿不到模型明文和业务数据。
- 形成完整的“加密模型 → 调度 → 联合证明 → 条件发钥 → 机密推理”演示。

NVIDIA 当前的机密容器参考架构就是 Kata + GPU Operator + Trustee/KBS，并要求证明成功后才释放模型密钥。[NVIDIA Confidential Containers](https://docs.nvidia.com/datacenter/cloud-native/confidential-containers/latest/)

## 五、最终验收矩阵

| 验收项 | L1 | L2 | L3 |
|---|---:|---:|---:|
| 普通模型推理 | 必须 | 必须 | 必须 |
| 加密模型包 | 必须 | 必须 | 必须 |
| 失败时拒绝发钥 | Mock 证据 | 真实证据 | 真实联合证据 |
| CPU TEE | 不验证 | 必须 | 必须 |
| GPU CC | 不验证 | 必须 | 必须 |
| 硬件 Attestation | 不验证 | 必须 | 必须 |
| KBS 条件发钥 | 接口/逻辑 | 真实 | 真实 |
| CVM 内解密 | 模拟边界 | 必须 | 必须 |
| Kubernetes/Kata | 不要求 | 不要求 | 必须 |
| 性能对比 | 流程基线 | CC 单节点 | 集群负载 |
| 可对客户声称硬件隔离 | 不可以 | 可以，限单节点 | 可以，限已验证集群 |

## 六、默认假设

- 当前没有 TDX/SEV-SNP + NVIDIA CC 的真实服务器。
- 当前目标是形成前期技术验证和客户演示，不承担生产上线。
- 第一阶段不自行开发密码算法、硬件验证器或生产 KMS。
- Mock 组件必须在界面、日志和文档中标记为 `demo-mock`。
- 模型、镜像、驱动、框架、测试脚本和请求集必须锁定版本。
- 正式采购前必须让服务器 OEM/NVIDIA 对完整软硬件组合进行兼容性确认。
- L1 完成后再申请单节点真实 CC 资源；L2 通过后再进入 Kubernetes 集群化，避免同时调试硬件、虚拟化、证明、KBS 和模型服务。
