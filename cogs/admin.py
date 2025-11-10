import config

from datetime import datetime
from discord import app_commands, Interaction, Client, TextChannel
from discord.ext import commands
from logger import logger
from typing import List

from src import auto_reception

#
# Helper functions
#
async def trigger_event(bot: Client, event: str):
	if event in config.EVENTS_TRIGGER:
		# note: does not stop event from triggering again
		# TODO: add optional argument to here and /trigger to bypass time based triggers (i.e. set event triggeed to true)
		target_channel: TextChannel = await bot.fetch_channel(config.NOTIFICATION_CHANNEL_ID)
		m = config.EVENTS_TRIGGER[event]["message"]
		if len(config.EVENTS_TRIGGER[event]['remindee']) > 0:
			m += "\n-# Also paging " + ', '.join(f"<@&{remindee}>" for remindee in config.EVENTS_TRIGGER[event]['remindee'])

		await target_channel.send(m)

		logger.info(f"Triggering event [{event}]")

#
# DISCORD COMMANDS
#

class Check(commands.Cog):
	def __init__(self, bot):
		self.bot = bot
		self.bot.tree.add_command(CheckGroup(name="check", description="Check bot information while it is running"))

class CheckGroup(app_commands.Group):
	@app_commands.command(name="queue", description="Check the queue")
	@app_commands.checks.has_permissions(administrator=True)
	async def queue(self, interaction: Interaction):
		checkin_queue = config.queue_cursor.execute("SELECT * FROM queue").fetchall()

		m = f"**Current queue has {len(checkin_queue)} items**\n"

		# change to raw
		m += "```"
		m += f"[{'checkout time':^13}] | [Room] | [CC]\n"
		m += ("-"*15) + "-|-" + ("-"*13) + "-|-" + ("-" * 13)
		m += "\n"
		for thread_id, message_id, user_id, end_time, cc_user_id, is_reservation in checkin_queue:
			thread_name = interaction.guild.get_thread(thread_id).name
			cc_user = interaction.client.get_user(cc_user_id)
			m += (f"[{datetime.strftime(datetime.fromtimestamp(end_time), '%I:%M:%S %p %z %Z')}] | "
			      f"{thread_name} | ")
			if cc_user is not None:
				m += f"{cc_user.name} ({cc_user.display_name})"

			m += "\n"
		m += "```"
		await interaction.response.send_message(m)


async def auto_complete_triggers(interaction: Interaction, current: str) -> List[app_commands.Choice[str]]:
	return [app_commands.Choice(name=choice_value, value=choice_value) for choice_value in config.EVENTS_TRIGGER.keys()]

class Misc(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

	@app_commands.command(name="trigger", description="Manually trigger an event")
	@app_commands.autocomplete(
		trigger=auto_complete_triggers
	)
	async def trigger(self, interaction: Interaction, trigger: str):
		logger.info(f"Manually triggering event [{trigger}]")
		await interaction.response.send_message("Done", delete_after=5)
		await trigger_event(self.bot, trigger)
