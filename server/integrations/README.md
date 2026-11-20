# Optional Home Assistant / n8n achievement announcements

The server writes each *new* achievement unlock to the `notification_outbox` table **in the same SQLite transaction as the unlock**. It only attempts outbound HTTP after the commit. Failure never delays device MQTT acknowledgements; the event remains queued and is retried with exponential backoff. Delivery is **at least once**, so downstream automations should use `event_key` to deduplicate if exact-once speech matters. Old achievements already unlocked before enabling the integration are **not** replayed automatically.

This bridge is disabled unless `PEDAL_WEBHOOK_URL` is supplied to the container.

1. In Home Assistant, create a webhook automation based on `home-assistant-automation.example.yaml`. Generate a long, unpredictable `webhook_id` and keep it secret. Set `local_only: true` for a local-only webhook.
2. Place `compose.webhook.example.yaml` in the existing `~/pedal/pedal-telemetry/` directory with the filename **`compose.override.yaml`**. If one already exists, merge this `backend.environment` entry into it, rather than overwriting it.
3. Add `PEDAL_WEBHOOK_URL=http://YOUR_HA_HOST:8123/api/webhook/YOUR_LONG_RANDOM_ID` to the existing `.env` on delta2, keeping it private (`chmod 600 .env`). The URL must be reachable *from inside the backend container*. Prefer a private HA hostname or IP. Do not use `localhost` to refer to HA in another container.
4. Run `docker compose up -d --no-deps backend` to apply the new env var. No published ports or network drivers are changed.
5. The next **new** achievement posts a JSON document like:

```json
{
  "event": "achievement_unlocked",
  "event_key": "achievement:century",
  "device_id": "bike-001",
  "occurred_ms": 1795123456000,
  "achievement": {"id":"century","name":"Century Club","icon":"💯"}
}
```

Because the webhook URL is a shared secret and currently uses plaintext HTTP in this example, use only a trusted internal network; use HTTPS where possible. The Home Assistant example creates a persistent notification rather than assuming an Echo/Hermes media-player entity exists. You can replace that action with an appropriate local TTS service when configured.

If you want announcements **off**, unset `PEDAL_WEBHOOK_URL` and recreate only the backend. Queued events remain in SQLite for later; disabling does not remove history.
