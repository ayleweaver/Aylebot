import discord
import config

from datetime import datetime
from discord import app_commands, Interaction, Client, TextChannel, Message, ui
from discord.ext import commands
from logger import logger

def _modal_add_checkbox_group(options: list):
	checkbox_group = ui.CheckboxGroup()
	for i, option in enumerate(options):
		checkbox_group.add_option(label=option)
	return checkbox_group


def _modal_create_select(options: list):
	select = ui.Select()
	for i, option in enumerate(options):
		select.add_option(label=option)

	return select

def _modal_create_radio(options: list):
	radio = ui.RadioGroup()
	for i, option in enumerate(options):
		radio.add_option(label=option)

	return radio

class ApplicationModel(ui.Modal, title="Position application"):
	age_verification = ui.Label(
		text="Are you over the age of 18?",
		description="The Weaver's Nest Hotel is an +18 NSFW venue. You must be over the age of 18 to work here.",
		component=_modal_create_radio(["Yes", "No"])
	)
	ign_field = ui.Label(text="In-game Name", component=ui.TextInput(required=True))

	role_selection = ui.Label(
		text="Role",
		component=_modal_add_checkbox_group([
			"[SFW] Bartender",
			"[SFW] Reception",
			"[SFW / NSFW] Courtesan"
		])
	)

	date_available_selection = ui.Label(
		text="Courtesan",
		description="Which day will you be availalbe in",
		component=_modal_add_checkbox_group([
			"Saturday",
			"Sunday",
		])
	)

	intr_hour_available_selection = ui.Label(
		text="Interview Hour",
		description="When are you available for contact?",
		component=_modal_create_select([datetime(year=1, month=1, day=1, hour=i).strftime("%I:%M %p") for i in range(24)])
	)

	def __init__(self, bot):
		super().__init__()
		self.bot: Client = bot
	async def on_submit(self, interaction: Interaction) -> None:
		logger.info(f"A job application is received for {interaction.user.display_name} ({interaction.user.display_name})")
		embed = discord.Embed(title="New Application", description="A new application has been submitted.")

		embed.add_field(name="User", value=f"{interaction.user} ({interaction.user.display_name})", inline=False)
		embed.add_field(name="Over 18?", value=f"{self.age_verification.component.value}", inline=False)
		embed.add_field(name="Day", value=f"{self.ign_field.component.value}", inline=False)
		for role_data in [self.role_selection, self.date_available_selection]:
			embed.add_field(name=role_data.text, value=', '.join(role_data.component.values), inline=False)
		embed.add_field(name="Best Interview Time", value=f"{self.intr_hour_available_selection.component.values}", inline=False)

		await interaction.response.defer()
		await self.bot.get_channel(config.CHANNEL_ID_PRIVATE_JOB_APPLICATION).send(
			embed=embed
		)
		await interaction.followup.send_messsage("Your submission is sent!", ephemeral=True)

	async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
		await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)
		logger.error(f"Exception when submitting an application. {type(error)}: {error}")


class JobApplication(commands.GroupCog):
	def __init__(self, bot):
		self.bot: Client = bot
	@app_commands.command(name="apply", description="Apply to a position at the Weaver's Nest")
	async def apply(self, interaction: Interaction):
		await interaction.response.send_modal(ApplicationModel(self.bot))