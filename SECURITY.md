# Security & Threat Model

1. **Webhook Authenticity:** Every `POST /webhook/whatsapp` request is verified against `X-Hub-Signature-256` using `hmac.compare_digest`.
2. **Strict Allowlist:** Only phone numbers listed in `WHATSAPP_ALLOWLIST` can invoke the agent. An empty allowlist denies all senders.
3. **Human-in-the-Loop (HITL) Isolation:** Approval codes are bound to the originating sender and expire after 5 minutes.
4. **Zero Open Ports:** Binds to `127.0.0.1:8082` by default; expose `/webhook/whatsapp` via Cloudflare Tunnel and keep `/demo` private.
