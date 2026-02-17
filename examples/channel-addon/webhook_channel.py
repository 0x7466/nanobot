"""
Example channel addon: WebhookChannel

This demonstrates how to create a custom channel that receives messages
via HTTP webhooks.

To use this example:
1. Copy this file to your own package
2. Register the entry point in pyproject.toml
3. Configure in nanobot config.yaml
4. Install your package

Entry point registration (pyproject.toml):
    [project.entry-points."nanobot.channels"]
    webhook = "my_package.webhook_channel:WebhookChannel"

Config (config.yaml):
    channels:
      addons:
        webhook:
          enabled: true
          port: 8080
          secret: "your-webhook-secret"  # Optional
"""

import asyncio
from typing import Any

from loguru import logger

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    web = None  # type: ignore

from nanobot.channels import BaseChannel
from nanobot.bus.events import OutboundMessage


class WebhookChannel(BaseChannel):
    """
    Example webhook channel addon.
    
    Receives messages via HTTP POST to /webhook endpoint.
    Can be used to integrate with external services, custom apps, etc.
    """
    
    name = "webhook"
    version = "1.0.0"
    description = "HTTP webhook channel for external integrations"
    author = "Your Name"
    requires = ["aiohttp"]  # Optional dependencies
    
    def __init__(self, config: dict[str, Any], bus: Any):
        """
        Initialize webhook channel.
        
        Args:
            config: Channel configuration from channels.addons.webhook
            bus: MessageBus instance for communication
        """
        super().__init__(config, bus)
        
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "WebhookChannel requires 'aiohttp'. "
                "Install with: pip install aiohttp"
            )
        
        self.port = config.get("port", 8080)
        self.host = config.get("host", "0.0.0.0")
        self.secret = config.get("secret", "")
        self.path = config.get("path", "/webhook")
        
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
    
    async def start(self) -> None:
        """
        Start the webhook server.
        
        Sets up HTTP server and begins listening for incoming webhooks.
        This runs until stop() is called.
        """
        self._app = web.Application()
        self._app.router.add_post(self.path, self._handle_webhook)
        
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        
        self._running = True
        logger.info(
            f"Webhook channel '{self.name}' listening on "
            f"http://{self.host}:{self.port}{self.path}"
        )
        
        # Keep running until stopped
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Webhook channel cancelled")
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the webhook server and clean up resources."""
        logger.info(f"Stopping webhook channel '{self.name}'...")
        self._running = False
        
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        
        self._site = None
        self._runner = None
        self._app = None
        
        logger.info(f"Webhook channel '{self.name}' stopped")
    
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.
        
        Note: This example channel is inbound-only (receives webhooks).
        For a bidirectional channel, implement the outbound logic here.
        
        Args:
            msg: The message to send
        """
        # This example is inbound-only
        # For outbound, you might:
        # - Make HTTP requests to external APIs
        # - Send to websocket connections
        # - Queue messages for processing
        logger.info(
            f"[{self.name}] Outbound message would be sent to {msg.chat_id}: "
            f"{msg.content[:100]}..."
        )
    
    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """
        Handle incoming webhook POST requests.
        
        Expected JSON body:
        {
            "sender_id": "user123",
            "chat_id": "room456", 
            "message": "Hello bot!",
            "metadata": {...}  # optional
        }
        
        Args:
            request: aiohttp request object
            
        Returns:
            HTTP response
        """
        # Verify secret if configured
        if self.secret:
            header_secret = request.headers.get("X-Webhook-Secret", "")
            if header_secret != self.secret:
                logger.warning("Webhook request with invalid secret")
                return web.Response(status=401, text="Unauthorized")
        
        try:
            data = await request.json()
        except Exception as e:
            logger.error(f"Invalid JSON in webhook: {e}")
            return web.Response(status=400, text="Invalid JSON")
        
        sender_id = data.get("sender_id", "anonymous")
        chat_id = data.get("chat_id", "default")
        message = data.get("message", "")
        metadata = data.get("metadata", {})
        
        # Check if sender is allowed (uses BaseChannel.is_allowed)
        if not self.is_allowed(sender_id):
            logger.warning(f"Webhook from disallowed sender: {sender_id}")
            return web.Response(status=403, text="Forbidden")
        
        # Process the message through the bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=message,
            metadata={
                "source": "webhook",
                **metadata
            }
        )
        
        logger.debug(f"Webhook processed from {sender_id}: {message[:50]}...")
        return web.Response(status=200, text="OK")


# For testing the channel standalone
if __name__ == "__main__":
    # Simple test setup
    from nanobot.bus.queue import MessageBus
    
    async def test():
        bus = MessageBus()
        config = {
            "enabled": True,
            "port": 8080,
            "secret": "test-secret"
        }
        
        channel = WebhookChannel(config, bus)
        
        # Start with timeout for testing
        try:
            await asyncio.wait_for(channel.start(), timeout=5.0)
        except asyncio.TimeoutError:
            print("Channel started successfully (timeout expected)")
        
        await channel.stop()
        print("Channel stopped")
    
    asyncio.run(test())
