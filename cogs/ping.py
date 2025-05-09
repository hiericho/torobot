# /cogs/utility_cog.py

import discord
from discord import app_commands, Interaction
from discord.ext import commands
import random
import time # For a slightly more interactive feel, though bot.latency is the main thing

logger = discord.utils.logging.getLogger('discord') # Use discord's logging

# --- Cute Aesthetic Elements ---
CUTE_PONG_EMOJIS = ["🌸", "💖", "✨", "🎀", "💌", "💫", "🍭", "🌙", "🐾"]
CUTE_PING_MESSAGES = [
    "Boop! Checking our connection... ",
    "Sending out a little spark... ",
    "Let's see how fast my heart beats for you... ",
    "Measuring the distance to the stars and back... ",
    "Just a moment, fetching some sparkles... "
]
CUTE_PONG_RESPONSES = [
    "My heart beats for you at:",
    "Connection sparkling at:",
    "Roundtrip complete! Latency is:",
    "Got a signal! We're connected at:",
    "Everything's A-OK! Current pulse:"
]
PASTEL_COLORS = [
    discord.Color.from_rgb(255, 182, 193),  # Light Pink
    discord.Color.from_rgb(255, 204, 229),  # Lighter Pink
    discord.Color.from_rgb(204, 229, 255),  # Baby Blue
    discord.Color.from_rgb(229, 204, 255),  # Lavender
    discord.Color.from_rgb(204, 255, 229),  # Mint Green
    discord.Color.from_rgb(255, 229, 204),  # Peach
    discord.Color.from_rgb(255, 253, 208),  # Cream
]

class PingCog(commands.Cog, name="ping"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("pingCog loaded successfully!")

    @app_commands.command(name="ping", description="🌸 Check the bot's heartbeat with a cute response!")
    async def ping_command(self, interaction: Interaction):
        """A cute ping command."""
        
        # 1. Send an initial cute "pinging" message
        initial_message_text = random.choice(CUTE_PING_MESSAGES) + random.choice(CUTE_PONG_EMOJIS)
        # Using defer() and followup() for better UX if latency calculation were slow
        # For ping, it's super fast, but this is good practice.
        await interaction.response.defer(ephemeral=False) # Ephemeral False to show it to everyone

        # Simulate a tiny bit of work for the "measuring" feel (optional)
        # await asyncio.sleep(0.5) 

        # 2. Get latency
        latency_ms = round(self.bot.latency * 1000)

        # 3. Create the cute embed
        embed_color = random.choice(PASTEL_COLORS)
        pong_response_text = random.choice(CUTE_PONG_RESPONSES)
        
        embed = discord.Embed(
            title=f"{random.choice(CUTE_PONG_EMOJIS)} Pong! {random.choice(CUTE_PONG_EMOJIS)}",
            description=f"{pong_response_text}",
            color=embed_color
        )
        
        embed.add_field(
            name="💖 Heartbeat Latency", 
            value=f"```css\n{latency_ms} ms\n```", # css for slight styling
            inline=False
        )
        
        embed.set_footer(text=f"Stay sparkling, {interaction.user.display_name}! ✨")
        embed.timestamp = discord.utils.utcnow() # Optional: add a timestamp

        # 4. Send the final embed as a followup
        # If we didn't defer, we'd use interaction.edit_original_response(content=None, embed=embed)
        # after an initial interaction.response.send_message(initial_message_text)
        await interaction.followup.send(content=initial_message_text, embed=embed)
        logger.info(f"/ping command used by {interaction.user.name}. Latency: {latency_ms}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))