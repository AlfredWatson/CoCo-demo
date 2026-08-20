# L1 failure-injection matrix

`test_l1_primitives.py` is runnable without a downloaded model and currently proves AES-GCM round-trip, ciphertext tamper rejection, assertion signature rejection, and expiry rejection.

After the Compose deployment is live, run the following as service-level evidence and retain the raw HTTP status/output (never DEKs, prompts, or responses):

| Injection | Expected result |
|---|---|
| No assertion / Mock service unavailable | inference live, not-ready, no vLLM process |
| Expired assertion | broker returns 403; no DEK |
| Replayed nonce | broker returns 403; no DEK |
| Wrong image/model/config/policy claim | broker returns 403; no DEK |
| Change one ciphertext byte | gate not-ready; AES-GCM/hash rejection |
| Wrong DEK | gate not-ready; GCM tag rejection |
| Stop Key Broker then restart inference | remains not-ready; no bypass |
| Restart inference | a new challenge and assertion are required |

The benchmark helper records latency/error data only. It intentionally does not store the prompt or generated text.
