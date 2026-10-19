import os
import asyncio
import logging
from datetime import time
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks

from functions import (
    init_bot,
    get_line_combinations,
    get_starting_goalies,
    get_injury_report,
    resolve_team_slug,
    get_latest_github_release,
    format_release_announcement,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
TIMEZONE = "America/Los_Angeles"
GOALIES_CHANNEL_NAME = "starting-goalies"
INJURY_REPORT_CHANNEL_NAME = "injury-report"
UPDATES_CHANNEL_NAME = "updates"

GITHUB_REPO = os.getenv("GITHUB_REPO")   # e.g. "yourname/fantasy-hockey-bot"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") # optional; required for private repos

_TZ = ZoneInfo(TIMEZONE)
GOALIES_SCHEDULE_TIME = time(11, 0, tzinfo=_TZ)
INJURY_REPORT_SCHEDULE_TIME = time(22, 0, tzinfo=_TZ)


def main():
    """Initialize and run the Discord fantasy hockey bot."""
    bot = init_bot()

    async def _check_and_announce_release():
        """Post to #updates if a new GitHub release hasn't been announced there yet."""
        if not GITHUB_REPO:
            return
        try:
            release = await asyncio.to_thread(get_latest_github_release, GITHUB_REPO, GITHUB_TOKEN)
        except Exception as e:
            logger.warning(f"Failed to fetch GitHub release: {e}")
            return

        if release is None:
            return

        tag = release["tag_name"]

        guild = bot.guilds[0] if bot.guilds else None
        if not guild:
            return
        channel = discord.utils.get(guild.text_channels, name=UPDATES_CHANNEL_NAME)
        if not channel:
            logger.warning(f"Channel '{UPDATES_CHANNEL_NAME}' not found — skipping release announcement")
            return

        # Use channel history as the idempotency store — survives container restarts.
        async for message in channel.history(limit=50):
            if message.author == bot.user and tag in message.content:
                return

        try:
            await channel.send(format_release_announcement(release))
            logger.info(f"Announced release {tag}")
        except Exception as e:
            logger.error(f"Failed to send release announcement for {tag}: {e}")

    @bot.listen()
    async def on_ready():
        """Handle bot ready event - sync commands and start scheduled tasks."""
        try:
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

        await _check_and_announce_release()

        if not scheduled_goalies.is_running():
            scheduled_goalies.start()
        if not scheduled_injuries.is_running():
            scheduled_injuries.start()
        if not release_checker.is_running():
            release_checker.start()

    @bot.tree.command(name="beep", description="Test to make sure the bot is online")
    async def beep(interaction: discord.Interaction):
        await interaction.response.send_message("boop")

    def _build_response_with_mention(content: str, user_id: int) -> str:
        return f"{content}\n<@{user_id}>"

    @bot.tree.command(name="goalies", description="Returns projected starting goalies for the day")
    async def get_starting_goalies_command(interaction: discord.Interaction):
        try:
            content = await asyncio.to_thread(get_starting_goalies)
            await interaction.response.send_message(_build_response_with_mention(content, interaction.user.id))
        except Exception as e:
            logger.error(f"Error in goalies command: {e}")
            await interaction.response.send_message("Sorry, I couldn't fetch the starting goalies right now. Please try again later.")

    @bot.tree.command(name="injuries", description="Returns injury report for the day")
    async def get_injury_report_command(interaction: discord.Interaction):
        try:
            content = await asyncio.to_thread(get_injury_report)
            await interaction.response.send_message(_build_response_with_mention(content, interaction.user.id))
        except Exception as e:
            logger.error(f"Error in injuries command: {e}")
            await interaction.response.send_message("Sorry, I couldn't fetch the injury report right now. Please try again later.")

    @bot.tree.command(name="lines", description="Returns current starting lineup for a team")
    async def get_lines_command(interaction: discord.Interaction, team_name: str):
        slug = resolve_team_slug(team_name)
        if slug is None:
            await interaction.response.send_message(
                f"Couldn't find a team matching '{team_name}'. Try a team name, city, or abbreviation (e.g. `sharks`, `sjs`, `san jose`)."
            )
            return
        try:
            content = await asyncio.to_thread(get_line_combinations, slug)
            await interaction.response.send_message(_build_response_with_mention(content, interaction.user.id))
        except Exception as e:
            logger.error(f"Error in lines command for team '{team_name}' (slug: {slug}): {e}")
            await interaction.response.send_message(f"Sorry, I couldn't fetch the line combinations for '{team_name}'. Please try again later.")

    async def _send_scheduled_report(report_type: str, data_func, channel_name: str):
        """Send a scheduled report with error handling and retries."""
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                guild = bot.guilds[0] if bot.guilds else None
                if not guild:
                    logger.error("Bot is not in any guild")
                    return
                channel = discord.utils.get(guild.text_channels, name=channel_name)
                if not channel:
                    logger.error(f"Channel '{channel_name}' not found")
                    return

                content = await asyncio.to_thread(data_func)
                await channel.send(content)
                logger.info(f"Successfully sent scheduled {report_type} report")
                return

            except Exception as e:
                logger.warning(f"Attempt {attempt}/{max_retries} failed for {report_type} report: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(60)
                else:
                    logger.error(f"Failed to send {report_type} report after {max_retries} attempts")

    @tasks.loop(hours=1)
    async def release_checker():
        await _check_and_announce_release()

    @tasks.loop(time=GOALIES_SCHEDULE_TIME)
    async def scheduled_goalies():
        await _send_scheduled_report("goalies", get_starting_goalies, GOALIES_CHANNEL_NAME)

    @tasks.loop(time=INJURY_REPORT_SCHEDULE_TIME)
    async def scheduled_injuries():
        await _send_scheduled_report("injuries", get_injury_report, INJURY_REPORT_CHANNEL_NAME)

    bot.run(os.getenv("DISCORD_TOKEN"))


if __name__ == "__main__":
    main()
