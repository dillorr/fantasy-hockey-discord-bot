import discord
from discord.ext import commands


def init_bot() -> commands.Bot:
    """
    Initialize and configure the Discord bot with necessary intents and settings.
    
    Returns:
        commands.Bot: Configured Discord bot instance
    """
    # Enable necessary intents for bot functionality
    intents = discord.Intents.default()
    intents.message_content = True

    # Create bot instance with slash command support
    bot = commands.Bot(
        command_prefix=commands.when_mentioned,  # slash commands only; prefix never matches
        intents=intents,
        help_command=None,  # Disable traditional help since we're using slash commands
    )

    return bot
