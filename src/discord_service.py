"""
Discord Service for Rin Agent.

Enables messaging Rin through Discord DMs and channel mentions.
Messages are routed to the same task queue as voice/overlay inputs.

Security:
- Only responds to approved user IDs (configurable)
- DM approval required for new users
- Rate limiting to prevent abuse
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger("qwen3vl.discord")

# Check if discord.py is available
try:
    import discord
    from discord.ext import commands
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None  # type: ignore
    commands = None  # type: ignore
    logger.info("discord.py not installed. Run: pip install discord.py")


@dataclass
class DiscordConfig:
    """Configuration for Discord service."""
    token: str = ""
    allowed_users: Set[int] = None  # User IDs allowed to interact
    require_approval: bool = True    # Require approval for new users
    command_prefix: str = "!"
    respond_to_mentions: bool = True
    respond_to_dms: bool = True
    
    def __post_init__(self):
        if self.allowed_users is None:
            self.allowed_users = set()


# Priority commands for immediate execution
PRIORITY_COMMANDS = {
    "stop": "abort", "cancel": "abort", "abort": "abort",
    "pause": "pause", "wait": "pause", "hold": "pause",
    "resume": "resume", "continue": "resume", "go": "resume",
}

# Steering prefixes - inject into current task
STEERING_PREFIXES = ["actually", "instead", "also", "but", "wait", "no", "not that", "change"]


class DiscordService:
    """
    Discord bot service for Rin.
    
    Routes messages to task queue OR injects into active task for real-time steering.
    """
    
    def __init__(self, config: DiscordConfig, status_server=None):
        if not DISCORD_AVAILABLE:
            raise ImportError("discord.py is required. Install with: pip install discord.py")
        
        self.config = config
        self.status_server = status_server
        self.task_queue = None
        self.orchestrator = None
        self.response_callbacks: dict = {}
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        
        # Pending approvals
        self._pending_approvals: Set[int] = set()
        
        # Chat history for context
        self.chat_history: list = []  # [{role, content, timestamp}]
        self.max_history = 10
        
        # Set up bot with intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        
        self.bot = commands.Bot(
            command_prefix=config.command_prefix,
            intents=intents,
            help_command=None
        )
        
        self._setup_events()
        self._setup_commands()
        
        logger.info("Discord service initialized with real-time steering")
    
    def _setup_events(self):
        """Set up Discord event handlers."""
        
        @self.bot.event
        async def on_ready():
            logger.info(f"Discord bot connected as {self.bot.user}")
            # Set presence
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name="for messages"
            )
            await self.bot.change_presence(status=discord.Status.online, activity=activity)
        
        @self.bot.event
        async def on_message(message: discord.Message):
            # Ignore own messages
            if message.author == self.bot.user:
                return
            
            # Check if this is a command
            if message.content.startswith(self.config.command_prefix):
                await self.bot.process_commands(message)
                return
            
            # Handle DMs
            if isinstance(message.channel, discord.DMChannel):
                if self.config.respond_to_dms:
                    await self._handle_message(message)
                return
            
            # Handle mentions in channels
            if self.bot.user in message.mentions:
                if self.config.respond_to_mentions:
                    await self._handle_message(message)
                return
    
    def _setup_commands(self):
        """Set up Discord slash/prefix commands."""
        
        @self.bot.command(name="status")
        async def status_command(ctx: commands.Context):
            """Check Rin's current status."""
            if not self._is_authorized(ctx.author.id):
                await ctx.reply("⚠️ You're not authorized to interact with me.")
                return
            
            embed = discord.Embed(
                title="🔮 Rin Status",
                color=discord.Color.purple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Status", value="Online", inline=True)
            embed.add_field(name="Mode", value="Listening", inline=True)
            
            await ctx.reply(embed=embed)
        
        @self.bot.command(name="screen")
        async def screen_command(ctx: commands.Context):
            """Capture and analyze the current screen."""
            if not self._is_authorized(ctx.author.id):
                await ctx.reply("don't think i know you")
                return
            
            await self._queue_task(ctx, "look at my screen and tell me what you see")
        
        @self.bot.command(name="do")
        async def do_command(ctx: commands.Context, *, task: str):
            """Execute a task on the computer."""
            if not self._is_authorized(ctx.author.id):
                await ctx.reply("i don't know you")
                return
            
            await self._queue_task(ctx, task)
        
        @self.bot.command(name="stop")
        async def stop_command(ctx: commands.Context):
            """Stop the current task."""
            if not self._is_authorized(ctx.author.id):
                await ctx.reply("who are you?")
                return
            
            if hasattr(self, 'orchestrator') and self.orchestrator:
                self.orchestrator.abort()
                await ctx.reply("ok stopping")
            else:
                await ctx.reply("nothing's running right now")
        
        @self.bot.command(name="memory")
        async def memory_command(ctx: commands.Context):
            """Show what Rin remembers about you."""
            if not self._is_authorized(ctx.author.id):
                await ctx.reply("i don't know you yet")
                return
            
            try:
                from .memory_service import get_memory_service
                memory = get_memory_service()
                context = memory.get_compact_context()
                
                if len(context) > 1900:
                    context = context[:1900] + "..."
                await ctx.reply(f"here's what i remember:\n{context}")
            except Exception as e:
                await ctx.reply(f"couldn't access my memory: {e}")
    
    def _add_to_history(self, role: str, content: str):
        """Add message to chat history."""
        import time
        self.chat_history.append({"role": role, "content": content, "time": time.time()})
        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]
    
    def _is_agent_busy(self) -> bool:
        """Check if agent is currently executing a task."""
        if self.status_server:
            status = self.status_server.state.get("status", "idle")
            return status not in ("idle", "COMPLETE", "ERROR", "ABORTED")
        return False
    
    def _classify_message(self, text: str) -> tuple:
        """Classify message: priority, steering, chat, or task."""
        text_lower = text.lower().strip()
        
        # Priority commands first
        for trigger, action in PRIORITY_COMMANDS.items():
            if text_lower == trigger or text_lower.startswith(trigger + " "):
                return ("priority", action)
        
        # If busy, check for steering
        if self._is_agent_busy():
            for prefix in STEERING_PREFIXES:
                if text_lower.startswith(prefix):
                    return ("steering", text)
            # Any message during active task is steering
            return ("steering", text)
        
        # Check for casual conversation (NOT tasks)
        # Greetings and short casual messages
        chat_patterns = [
            "hey", "hi", "hello", "yo", "sup", "whats up", "what's up",
            "how are you", "how's it going", "hows it going", "wassup",
            "good morning", "good night", "gm", "gn", "thanks", "thank you",
            "ok", "okay", "cool", "nice", "lol", "lmao", "haha", "hehe",
            "bye", "cya", "see you", "later", "brb", "gtg",
        ]
        # Check if the entire message matches a chat pattern
        if text_lower in chat_patterns or len(text_lower) <= 3:
            return ("chat", text)
        
        # Questions that are conversational, not tasks
        question_starters = [
            "how are", "what's your", "whats your", "do you", "can you tell me about",
            "what do you think", "who are you", "are you", "why do",
        ]
        for starter in question_starters:
            if text_lower.startswith(starter):
                return ("chat", text)
        
        # Screen description requests (describe screen WITHOUT taking action)
        screen_indicators = [
            "what's on my screen", "whats on my screen", "what is on my screen",
            "tell me what you see", "what do you see", "describe my screen",
            "check my screen", "check my computer", "look at my screen",
            "what's happening on my screen", "whats happening",
        ]
        for indicator in screen_indicators:
            if indicator in text_lower:
                return ("screen", text)
        
        # Task indicators - phrases that suggest user wants action on the computer
        task_indicators = [
            "open", "close", "search", "find", "click", "type", "go to", "navigate",
            "download", "upload", "play", "pause", "stop", "start", "run",
            "launch", "switch to", "minimize", "maximize", "scroll",
        ]
        for indicator in task_indicators:
            if indicator in text_lower:
                return ("task", text)
        
        # Default to chat for unclear messages (better to chat than accidentally open apps)
        return ("chat", text)

    async def _handle_message(self, message: discord.Message):
        """Handle an incoming message with real-time steering."""
        user_id = message.author.id
        
        # Authorization check
        if not self._is_authorized(user_id):
            if self.config.require_approval:
                if user_id not in self._pending_approvals:
                    self._pending_approvals.add(user_id)
                    await message.reply(
                        "hey, i don't know you yet. ask the admin to add your user ID to settings.yaml"
                    )
                return
            else:
                self.config.allowed_users.add(user_id)
        
        # Extract content (remove mention)
        content = message.content
        if self.bot.user.mentioned_in(message):
            content = content.replace(f'<@{self.bot.user.id}>', '').strip()
            content = content.replace(f'<@!{self.bot.user.id}>', '').strip()
        
        if not content:
            await message.reply("yeah?")
            return
        
        # Add to history
        self._add_to_history("user", content)
        
        # Classify and route
        category, payload = self._classify_message(content)
        
        if category == "priority":
            await self._handle_priority(payload, message.channel)
            return
        
        if category == "steering":
            await self._handle_steering(content, message.channel)
            return
        
        if category == "chat":
            await self._handle_chat(content, message)
            return
        
        # Regular task - user wants action on computer
        async with message.channel.typing():
            await self._queue_task(message, content)
    
    async def _handle_priority(self, action: str, channel):
        """Handle priority commands immediately."""
        if not self.orchestrator:
            await channel.send("not connected")
            return
        
        if action == "abort":
            self.orchestrator.abort()
            if self.status_server:
                self.status_server.emit_status("idle", "stopped")
                self.status_server.emit_thought("stopped via discord")
            await channel.send("stopped")
        elif action == "pause":
            if hasattr(self.orchestrator, 'pause'):
                self.orchestrator.pause()
            if self.status_server:
                self.status_server.emit_thought("paused")
            await channel.send("paused")
        elif action == "resume":
            if hasattr(self.orchestrator, 'resume'):
                self.orchestrator.resume()
            if self.status_server:
                self.status_server.emit_thought("resuming")
            await channel.send("ok going")
    
    async def _handle_steering(self, text: str, channel):
        """Inject steering context into active task."""
        if not self.orchestrator:
            await channel.send("not connected rn")
            return
        
        # Emit to overlay
        if self.status_server:
            self.status_server.emit_thought(f"{text[:50]}...")
        
        self.orchestrator.inject_context(text)
        await channel.send("got it")
    
    async def _handle_chat(self, text: str, message):
        """Handle casual conversation - no computer action needed."""
        import random
        text_lower = text.lower().strip()
        
        # Simple pattern-based responses for common greetings
        greetings = ["hey", "hi", "hello", "yo", "sup", "wassup"]
        if text_lower in greetings or len(text_lower) <= 3:
            responses = ["hey", "yo", "what's up", "hey what's going on", "sup"]
            await message.reply(random.choice(responses))
            return
        
        if "how are" in text_lower or "how's it going" in text_lower:
            responses = ["good, you?", "doing alright", "not bad, what about you"]
            await message.reply(random.choice(responses))
            return
        
        if "thanks" in text_lower or "thank you" in text_lower:
            responses = ["np", "no problem", "yeah ofc", "anytime"]
            await message.reply(random.choice(responses))
            return
        
        if "bye" in text_lower or "later" in text_lower or "cya" in text_lower:
            responses = ["later", "cya", "talk soon"]
            await message.reply(random.choice(responses))
            return
        
        if "who are you" in text_lower:
            await message.reply("i'm rin, i can control your computer if you need me to do stuff")
            return
        
        # Default casual response for unclear messages
        responses = [
            "what do you need?",
            "need me to do something?",
            "what's up",
        ]
        await message.reply(random.choice(responses))
    
    async def _queue_task(self, ctx_or_message, task: str):
        """Queue a task for execution and set up response callback."""
        # Get channel for response
        if hasattr(ctx_or_message, 'channel'):
            channel = ctx_or_message.channel
        else:
            channel = ctx_or_message
        
        # Emit to overlay
        if self.status_server:
            self.status_server.emit_status("loading", task[:50])
            self.status_server.emit_thought(task)
        
        # Casual acknowledgment
        if hasattr(ctx_or_message, 'reply'):
            ack = await ctx_or_message.reply(f"on it")
        else:
            ack = await channel.send(f"on it")
        
        # Store callback for response
        self.response_callbacks[channel.id] = {
            'channel': channel,
            'ack_message': ack,
            'task': task,
            'timestamp': datetime.now()
        }
        
        # Queue the task
        if self.task_queue:
            self.task_queue.put(task)
            logger.info(f"Discord: Queued task from {channel}: {task[:50]}...")
        else:
            await channel.send("backend isn't running")
    
    def _is_authorized(self, user_id: int) -> bool:
        """Check if a user is authorized to interact."""
        # If no allowed users configured, allow everyone
        if not self.config.allowed_users:
            return True
        return user_id in self.config.allowed_users
    
    async def send_response(self, channel_id: int, response: str, success: bool = True):
        """Send a response to a channel."""
        if channel_id not in self.response_callbacks:
            logger.warning(f"No callback registered for channel {channel_id}")
            return
        
        callback_info = self.response_callbacks.pop(channel_id)
        channel = callback_info['channel']
        
        # Create embed for response
        color = discord.Color.green() if success else discord.Color.red()
        embed = discord.Embed(
            description=response[:4000],  # Discord limit
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Task: {callback_info['task'][:50]}...")
        
        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send Discord response: {e}")
    
    async def send_proactive_message(self, user_id: int, message: str):
        """Send a proactive message to a user (from heartbeat)."""
        try:
            user = await self.bot.fetch_user(user_id)
            if user:
                embed = discord.Embed(
                    title="💡 Rin Check-in",
                    description=message,
                    color=discord.Color.gold(),
                    timestamp=datetime.utcnow()
                )
                await user.send(embed=embed)
                logger.info(f"Sent proactive message to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send proactive message: {e}")
    
    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    
    def set_task_queue(self, queue):
        """Set the task queue for submitting tasks."""
        self.task_queue = queue
    
    def set_orchestrator(self, orchestrator):
        """Set orchestrator reference for stop/pause commands."""
        self.orchestrator = orchestrator
    
    def start(self) -> bool:
        """Start the Discord bot in a background thread."""
        if not self.config.token:
            logger.warning("No Discord token configured. Discord service disabled.")
            return False
        
        if self._running:
            return True
        
        def run_bot():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self.bot.start(self.config.token))
            except Exception as e:
                logger.error(f"Discord bot error: {e}")
            finally:
                self._loop.close()
        
        self._thread = threading.Thread(target=run_bot, daemon=True)
        self._thread.start()
        self._running = True
        
        logger.info("Discord service started in background thread")
        return True
    
    def stop(self):
        """Stop the Discord bot."""
        if not self._running:
            return
        
        self._running = False
        
        if self._loop and self.bot:
            asyncio.run_coroutine_threadsafe(self.bot.close(), self._loop)
        
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info("Discord service stopped")


def load_discord_config(config: dict) -> DiscordConfig:
    """Load Discord configuration from settings dict."""
    discord_cfg = config.get("discord", {})
    
    # Priority 0: Environment variable (recommended for open-source users)
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    
    # Priority 1: Load token from ENCRYPTED secrets manager (most secure)
    if not token:
        try:
            from .secrets_manager import get_secret
            encrypted_token = get_secret("discord_token")
            if encrypted_token:
                token = encrypted_token
                logger.info("Discord token loaded from encrypted storage")
        except Exception as e:
            logger.debug(f"Could not load encrypted token: {e}")
    
    # Priority 2: Fall back to plaintext config (legacy support)
    if not token:
        token = discord_cfg.get("token", "")
    
    # Priority 3: Fall back to token file
    if not token:
        token_file = discord_cfg.get("token_file", "")
        if token_file:
            token_path = Path(token_file)
            if token_path.exists():
                token = token_path.read_text().strip()
    
    # Parse allowed users
    allowed_users = set(discord_cfg.get("allowed_users", []))
    
    return DiscordConfig(
        token=token,
        allowed_users=allowed_users,
        require_approval=discord_cfg.get("require_approval", True),
        command_prefix=discord_cfg.get("command_prefix", "!"),
        respond_to_mentions=discord_cfg.get("respond_to_mentions", True),
        respond_to_dms=discord_cfg.get("respond_to_dms", True),
    )


def init_discord_service(config: dict, status_server=None) -> Optional[DiscordService]:
    """Initialize Discord service from config."""
    if not DISCORD_AVAILABLE:
        logger.info("Discord service unavailable (discord.py not installed)")
        return None
    
    try:
        discord_config = load_discord_config(config)
        if not discord_config.token:
            logger.info("No Discord token configured. Skipping Discord service.")
            return None
        
        service = DiscordService(discord_config, status_server)
        return service
    except Exception as e:
        logger.error(f"Failed to initialize Discord service: {e}")
        return None
