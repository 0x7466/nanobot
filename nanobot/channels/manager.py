"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.
    
    Responsibilities:
    - Initialize enabled core channels (Telegram, WhatsApp, etc.)
    - Load and initialize addon channels via entry points
    - Start/stop channels
    - Route outbound messages
    """
    
    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._addon_channels: dict[str, type[BaseChannel]] = {}  # Registry of discovered addons
        
        self._init_channels()
    
    def _init_channels(self) -> None:
        """Initialize all channels (core + addons)."""
        self._load_core_channels()
        self._load_addon_channels()
    
    def _load_core_channels(self) -> None:
        """Initialize built-in core channels based on config."""
        core_channels = [
            ("telegram", "nanobot.channels.telegram", "TelegramChannel", 
             lambda cfg, bus: self._init_telegram(cfg, bus)),
            ("whatsapp", "nanobot.channels.whatsapp", "WhatsAppChannel",
             lambda cfg, bus: self._init_whatsapp(cfg, bus)),
            ("discord", "nanobot.channels.discord", "DiscordChannel",
             lambda cfg, bus: self._init_discord(cfg, bus)),
            ("feishu", "nanobot.channels.feishu", "FeishuChannel",
             lambda cfg, bus: self._init_feishu(cfg, bus)),
            ("mochat", "nanobot.channels.mochat", "MochatChannel",
             lambda cfg, bus: self._init_mochat(cfg, bus)),
            ("dingtalk", "nanobot.channels.dingtalk", "DingTalkChannel",
             lambda cfg, bus: self._init_dingtalk(cfg, bus)),
            ("email", "nanobot.channels.email", "EmailChannel",
             lambda cfg, bus: self._init_email(cfg, bus)),
            ("slack", "nanobot.channels.slack", "SlackChannel",
             lambda cfg, bus: self._init_slack(cfg, bus)),
            ("qq", "nanobot.channels.qq", "QQChannel",
             lambda cfg, bus: self._init_qq(cfg, bus)),
        ]
        
        for name, module_path, class_name, initializer in core_channels:
            config_obj = getattr(self.config.channels, name, None)
            if config_obj and getattr(config_obj, "enabled", False):
                try:
                    initializer(config_obj, self.bus)
                    logger.info(f"Core channel '{name}' enabled")
                except ImportError as e:
                    logger.warning(f"Core channel '{name}' not available: {e}")
                except Exception as e:
                    logger.error(f"Failed to initialize core channel '{name}': {e}")
    
    def _load_addon_channels(self) -> None:
        """Discover and load addon channels via Python entry points."""
        try:
            import importlib.metadata as metadata
            
            entry_points = metadata.entry_points(group="nanobot.channels")
            
            for ep in entry_points:
                channel_name = ep.name
                
                # Check if this addon is enabled in config
                from nanobot.config.schema import AddonChannelConfig
                addon_config = self.config.channels.addons.get(channel_name)
                
                # Handle both dict and AddonChannelConfig objects
                if isinstance(addon_config, dict):
                    if not addon_config.get("enabled", False):
                        continue
                    config_dict = addon_config.get("config", {})
                elif isinstance(addon_config, AddonChannelConfig):
                    if not addon_config.enabled:
                        continue
                    config_dict = addon_config.config
                else:
                    # No config found for this addon
                    continue
                
                try:
                    channel_class = ep.load()
                    
                    # Validate it's a proper BaseChannel subclass
                    if not isinstance(channel_class, type) or not issubclass(channel_class, BaseChannel):
                        logger.warning(f"Addon '{channel_name}' is not a valid BaseChannel subclass")
                        continue
                    
                    # Store in registry
                    self._addon_channels[channel_name] = channel_class
                    
                    # Instantiate with config dict
                    channel_instance = channel_class(config_dict, self.bus)
                    self.channels[channel_name] = channel_instance
                    
                    logger.info(
                        f"Addon channel '{channel_name}' enabled "
                        f"({channel_class.__module__}.{channel_class.__name__})"
                    )
                    
                except Exception as e:
                    logger.error(f"Failed to load addon channel '{channel_name}': {e}")
                    
        except ImportError:
            logger.debug("importlib.metadata not available, skipping addon discovery")
    
    # Core channel initializers
    def _init_telegram(self, config, bus):
        from nanobot.channels.telegram import TelegramChannel
        self.channels["telegram"] = TelegramChannel(
            config, bus, groq_api_key=self.config.providers.groq.api_key
        )
    
    def _init_whatsapp(self, config, bus):
        from nanobot.channels.whatsapp import WhatsAppChannel
        self.channels["whatsapp"] = WhatsAppChannel(config, bus)
    
    def _init_discord(self, config, bus):
        from nanobot.channels.discord import DiscordChannel
        self.channels["discord"] = DiscordChannel(config, bus)
    
    def _init_feishu(self, config, bus):
        from nanobot.channels.feishu import FeishuChannel
        self.channels["feishu"] = FeishuChannel(config, bus)
    
    def _init_mochat(self, config, bus):
        from nanobot.channels.mochat import MochatChannel
        self.channels["mochat"] = MochatChannel(config, bus)
    
    def _init_dingtalk(self, config, bus):
        from nanobot.channels.dingtalk import DingTalkChannel
        self.channels["dingtalk"] = DingTalkChannel(config, bus)
    
    def _init_email(self, config, bus):
        from nanobot.channels.email import EmailChannel
        self.channels["email"] = EmailChannel(config, bus)
    
    def _init_slack(self, config, bus):
        from nanobot.channels.slack import SlackChannel
        self.channels["slack"] = SlackChannel(config, bus)
    
    def _init_qq(self, config, bus):
        from nanobot.channels.qq import QQChannel
        self.channels["qq"] = QQChannel(config, bus)
    
    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error(f"Failed to start channel {name}: {e}")

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return
        
        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        
        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            logger.info(f"Starting {name} channel...")
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))
        
        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")
        
        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        
        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"Stopped {name} channel")
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")
    
    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")
        
        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )
                
                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error(f"Error sending to {msg.channel}: {e}")
                else:
                    logger.warning(f"Unknown channel: {msg.channel}")
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
    
    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)
    
    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running
            }
            for name, channel in self.channels.items()
        }
    
    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
    
    async def send_to_channel(self, channel_name: str, message: OutboundMessage) -> None:
        """Send a message to a specific channel.
        
        Args:
            channel_name: Name of the channel to send to.
            message: The message to send.
            
        Raises:
            ValueError: If the channel doesn't exist.
        """
        channel = self.channels.get(channel_name)
        if not channel:
            raise ValueError(f"Channel '{channel_name}' not found")
        
        await channel.send(message)
    
    def list_available_channels(self) -> list[str]:
        """List all available channels (core + discovered addons).
        
        Returns:
            List of all channel names that are available.
        """
        available = set(self.channels.keys())
        
        # Add discovered addon channels that aren't loaded
        try:
            import importlib.metadata as metadata
            entry_points = metadata.entry_points(group="nanobot.channels")
            for ep in entry_points:
                available.add(ep.name)
        except ImportError:
            pass
        
        return sorted(list(available))
    
    def get_channel_info(self, channel_name: str) -> dict[str, Any] | None:
        """Get metadata information about a channel.
        
        Args:
            channel_name: Name of the channel.
            
        Returns:
            Dict with channel metadata, or None if channel doesn't exist.
        """
        # Check if it's a loaded channel instance
        if channel_name in self.channels:
            channel = self.channels[channel_name]
            return {
                "name": channel.name,
                "version": getattr(channel, "version", "unknown"),
                "description": getattr(channel, "description", ""),
                "author": getattr(channel, "author", ""),
                "enabled": True,
                "loaded": True,
            }
        
        # Check if it's a discovered addon that's not loaded
        if channel_name in self._addon_channels:
            channel_class = self._addon_channels[channel_name]
            return {
                "name": getattr(channel_class, "name", channel_name),
                "version": getattr(channel_class, "version", "unknown"),
                "description": getattr(channel_class, "description", ""),
                "author": getattr(channel_class, "author", ""),
                "enabled": False,
                "loaded": False,
            }
        
        # Try to discover it without loading
        try:
            import importlib.metadata as metadata
            entry_points = metadata.entry_points(group="nanobot.channels")
            for ep in entry_points:
                if ep.name == channel_name:
                    try:
                        channel_class = ep.load()
                        if issubclass(channel_class, BaseChannel):
                            return {
                                "name": getattr(channel_class, "name", channel_name),
                                "version": getattr(channel_class, "version", "unknown"),
                                "description": getattr(channel_class, "description", ""),
                                "author": getattr(channel_class, "author", ""),
                                "enabled": False,
                                "loaded": False,
                            }
                    except Exception:
                        pass
                    break
        except ImportError:
            pass
        
        return None
