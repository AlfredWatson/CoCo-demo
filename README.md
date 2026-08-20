# 机密计算 L1 逻辑 PoC

这是 [PLAN.md](PLAN.md) 所定义的 **L1 `logic-only`** 演示：加密模型、条件发钥、仅在 `tmpfs` 解密、失败时 not-ready，以及 OpenAI 兼容推理接口。它不提供 TDX/SEV-SNP、GPU CC 或硬件 Attestation；不能声称宿主机管理员无法读取内存。

## 安全边界

- `mock-attestation` 只签发 `environment=demo-mock` assertion；它不是真实 TEE quote。
- `key-broker` 校验签名、nonce（单次使用）、过期时间、镜像摘要、模型密文摘要、推理配置摘要和策略版本，之后才返回 DEK。
- DEK 与签名密钥只挂载进控制面容器，不进入 inference 镜像或环境变量。DEK 从内存响应写入 `/run/model` 的 tmpfs，解密后立即删除该文件。
- 加密工具默认**不删除原始模型**，避免意外数据丢失。人工核验密文、哈希和恢复能力后，再按本组织流程删除原始副本。

## 模型下载完成后的首次准备

模型目录不要放进本仓库。以下命令会创建密文与仅限本机的 Demo 密钥；这些路径已被 `.gitignore` 排除：

先构建镜像并取得其不可变 digest；随后运行下面的准备器。它在 `tmpfs` 中打包明文模型、生成本机私有 DEK 与 Mock 签名密钥、写入密文和匹配的策略。不要使用可变 image tag 代替 digest：

```bash
.venv/bin/python scripts/prepare_l1.py \
  --model-dir /absolute/path/to/Qwen2.5-0.5B-Instruct \
  --image-digest sha256:replace-with-resolved-inference-image-digest
```

## 启动与验证

```bash
docker compose -f compose/compose.yaml up --build
curl -f http://127.0.0.1:8000/health/live
curl -f http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"/run/model/model","messages":[{"role":"user","content":"用一句话说明 L1 是什么。"}],"temperature":0,"max_tokens":128}'
```

无 assertion、错误策略、篡改密文或不可达 Broker 时，`/health/live` 仍返回 200，但 `/health/ready` 与推理接口必须返回 503。详细失败注入清单见 `tests/`；先运行：

```bash
.venv/bin/python -m unittest tests/test_l1_primitives.py
```

完成普通与加密版服务后，运行相同参数的基准：

```bash
.venv/bin/python benchmark/run.py --model /run/model/model --output artifacts/encrypted.jsonl
```

## 尚待真实模型后的工作

需要在模型就绪后实际完成 Docker GPU smoke、镜像 digest 锁定、Trustee/KBS 本地 Compose、30×{1,4,8} 并发基准、以及全部服务级失败注入。它们不能用静态脚本替代为“已通过”的结论。
