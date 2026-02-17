# Webhook Channel Example

This is a complete example of a nanobot channel addon that receives messages via HTTP webhooks.

## Installation

```bash
# Install in development mode
pip install -e .

# Or build and install
python -m build
pip install dist/nanobot_webhook_example-*.whl
```

## Configuration

Add to your `config.yaml`:

```yaml
channels:
  addons:
    webhook-example:
      enabled: true
      port: 8080
      host: "0.0.0.0"
      path: "/webhook"
      secret: "your-webhook-secret"  # Optional: verify X-Webhook-Secret header
      allow_from: []  # Optional: restrict to specific sender IDs
```

## Usage

Send a POST request to trigger the bot:

```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-webhook-secret" \
  -d '{
    "sender_id": "user123",
    "chat_id": "room456",
    "message": "Hello bot!"
  }'
```

## Webhook Format

Request body (JSON):

```json
{
  "sender_id": "unique-user-id",
  "chat_id": "conversation-id",
  "message": "Text message to the bot",
  "metadata": {
    "extra": "optional custom data"
  }
}
```

## Development

This example demonstrates:

- Entry point registration (`pyproject.toml`)
- `BaseChannel` subclass implementation
- Async start/stop lifecycle
- Security (optional secret validation)
- Permission checking (`is_allowed`)

Use this as a template for your own channel addons!
