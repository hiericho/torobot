import discord
from discord.ui import View, Button
from typing import List


class EmbedPaginator(View):
    def __init__(self, pages: List[discord.Embed], timeout: float = 90.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
        self.total_pages = len(pages)
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True  # Allow all users — you can limit by user ID if needed

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)

    async def interaction_handler(self, interaction: discord.Interaction, action: str):
        if action == "first_page":
            self.current_page = 0
        elif action == "prev_page" and self.current_page > 0:
            self.current_page -= 1
        elif action == "next_page" and self.current_page < self.total_pages - 1:
            self.current_page += 1
        elif action == "last_page":
            self.current_page = self.total_pages - 1

        embed = self.pages[self.current_page]
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.total_pages}")
        await interaction.response.edit_message(embed=embed, view=self)

    async def send(self, interaction: discord.Interaction):
        embed = self.pages[self.current_page]
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.total_pages}")
        self.message = await interaction.followup.send(embed=embed, view=self)

    @discord.ui.button(label="⏪ First", style=discord.ButtonStyle.secondary, row=0)
    async def first(self, interaction: discord.Interaction, _button: Button):
        await self.interaction_handler(interaction, "first_page")

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev(self, interaction: discord.Interaction, _button: Button):
        await self.interaction_handler(interaction, "prev_page")

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction: discord.Interaction, _button: Button):
        await self.interaction_handler(interaction, "next_page")

    @discord.ui.button(label="Last ⏩", style=discord.ButtonStyle.secondary, row=1)
    async def last(self, interaction: discord.Interaction, _button: Button):
        await self.interaction_handler(interaction, "last_page")
