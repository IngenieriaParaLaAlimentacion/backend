# ADR-0027: OpenRouter free inference

Status: Accepted with the OpenRouter migration.

### Context

Receipt extraction and recipe generation share ILlmClient. The previous
implementation called Google directly. We need configuration-based model
switching and strictly free inference.

### Decision

Use OpenRouter through httpx behind ILlmClient. Select explicit, qualified
:free models and hosting providers through environment configuration.
Call the configured model IDs directly; send zero price limits and explicit
provider restrictions on every request. There is no runtime catalogue fetch,
metadata cache or refresh lock. Verify workload support when configuring models.
No endpoint satisfying request constraints means AI unavailable. There is no
paid or direct-service fallback. Gemini can be configured only if an eligible free variant exists.

Do not enable random free-model routing. Receipt images and recipe context
must satisfy the selected endpoint's current data policy before qualification.
No model or provider is enabled by default.

Retry/fallback attempts share one small completion budget. Receipt processing
has a 60-second backend deadline; recipe generation retains its 90-second
default total deadline. Cancellation propagates without starting new attempts.
HTTP deadlines cannot guarantee cancellation of work already accepted upstream.

Recipe generation quota exhaustion and temporary unavailability have canonical
API errors. Receipt provider failures and deadline expiry retain HTTP 200 with
an empty proposal and manual-entry guidance. Invalid recipe output
retains domain validation and existing generation failure behavior.

### Consequences

Provider/model changes need configuration and workload qualification, not
client releases. Free availability and account quotas limit capacity; no
throughput guarantee follows. Switching free models does not increase the
OpenRouter account quota. No global usage ledger or DB migration is introduced.

This supersedes the direct-Gemini integration choice in ADR-0024. Nutrition,
stock, persistence, permissions and manual review remain backend/domain rules.

### References

- [Free model variants](https://openrouter.ai/docs/guides/routing/model-variants/free)
- [Provider routing and price ceilings](https://openrouter.ai/docs/guides/routing/provider-selection)
- [Structured output support](https://openrouter.ai/docs/guides/features/structured-outputs)
- [Account limits](https://openrouter.ai/docs/api_reference/limits)
- [Data handling](https://openrouter.ai/docs/guides/privacy/data-collection)

Model availability is dated evidence and must be rechecked before activation.

### Activation status (2026-10-25)

This workspace has no OpenRouter key or model/provider configuration, and no
endpoint has passed live inference qualification. Receipt and recipe inference
remain unavailable with the default empty configuration.

The refreshed public catalogue lists 17 explicit `:free` IDs and no free Gemini
variant. The [NVIDIA Nemotron vision candidate](https://openrouter.ai/nvidia/nemotron-3.5-super-vl:free)
prohibits personal or confidential input. The [Dots vision candidate](https://openrouter.ai/dots-studio/dots-3-note-preview:free)
retires on December 31, 2026. Neither candidate is approved for activation by
catalogue evidence alone. Recheck policy, lifecycle, exact schemas, Spanish task
quality, latency and observed zero cost before enabling either workload.

### Receipt quantity compatibility

Local extraction validation preserves the printed-quantity parsing retained in
Agustina's PR #211: numeric text with comma/dot decimals and dot thousands
separators is accepted, while unusable quantities become null without losing
valid receipt lines. Provider requests still ask for numeric or null quantities.
The shared quantity parser remains authoritative for normalization and rounding.

Local extraction ignores extra model fields, preserving existing receipt
compatibility. Malformed required line structure still returns the manual-entry
fallback. The strict provider request schema remains closed independently of
this tolerant local parsing.
