import discord
import config

from datetime import datetime
from discord import app_commands, Interaction, Client, TextChannel, Message
from discord.ext import commands
from logger import logger
from typing import List
from pathlib import Path

from src import auto_reception

#
# Helper functions
#
async def trigger_event(bot: Client, event: str, set_event:bool=False):
	"""
	manually trigger an event

	Args:
		bot (Client): The discord client object
		event (str): the event string
		set_event (bool): set the event to true when set

	Returns:
		None
	"""
	if event in config.EVENTS_TRIGGER:
		target_channel: TextChannel = await bot.fetch_channel(config.NOTIFICATION_CHANNEL_ID)
		m = config.EVENTS_TRIGGER[event]["message"]
		if len(config.EVENTS_TRIGGER[event]['remindee']) > 0:
			m += "\n-# Also paging " + ', '.join(f"<@&{remindee}>" for remindee in config.EVENTS_TRIGGER[event]['remindee'])

		await target_channel.send(m)

		logger.info(f"Triggering event [{event}]")
		if set_event:
			logger.info(f"Event [{event}] is now true")
			config.EVENTS_TRIGGER[event]["triggered"] = True

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
		self.bot: commands.Bot = bot
		self.spammer_content_directory = "spammer_content"
		self.spammer_content_path: Path = Path.cwd() / self.spammer_content_directory

		if not self.spammer_content_path.exists():
			self.spammer_content_path.mkdir()

	@app_commands.command(name="trigger", description="Manually trigger an event")
	@app_commands.autocomplete(
		trigger=auto_complete_triggers
	)
	async def trigger(self, interaction: Interaction, trigger: str):
		logger.info(f"Manually triggering event [{trigger}]")
		await interaction.response.send_message("Done", delete_after=5)
		await trigger_event(self.bot, trigger)

	@commands.Cog.listener()
	async def on_message(self, message: Message):
		if message.channel.id == config.HONEYPOT_CHANNEL_ID:
			author = message.author
			message_time = message.created_at

			spammer_content_filename = self.spammer_content_path / f"{author.id}.txt"
			logger.info(f"Spammer detected as {author.display_name} ({author.name}, ID: {author.id})")

			with spammer_content_filename.open("a+") as f:
				f.write(f"at {message_time.ctime()} ({message_time})\n")
				f.write(message.content)
				f.write("\n\n")

			logger.info(f"Spammer content has been saved to {spammer_content_filename}")
			server_owner_id = message.guild.owner_id
			server_owner = self.bot.get_user(server_owner_id)
			try:

				# send message to user, in case that if the user is a real user
				await author.send((
					"Hello,\n"
					f"If you are receiving this message, you have been banned from `{message.guild.name}` for "
					"**suspicions of being a spam bot**.\n\n"
					f"If you think this ban was made in error, please contact {server_owner.display_name} (`{server_owner.name}`)."
				))
				await author.ban(delete_message_days=7, reason="Auto-mod banned via honeypot channel.")

				# send message to server owner, notifying of auto ban
				await server_owner.send((
					"## A user was banned via honeypot channel.\n"
					f"User {author.display_name} ({author.name}, ID: {author.id}) was banned.\n"
					"Message conntent (up to 200 characters):\n"
					f"`{message.content[:200]}`"
				))
			except discord.Forbidden:
				await server_owner.send((
					"## A user sent a message in the honeypot channel.\n"
					"### I do not have persmission to ban them.\n"
					f"User {author.display_name} ({author.name}, ID: {author.id}) was typing in the honeypot channel.\n\n"
					"Message conntent (up to 200 characters):\n"
					f"`{message.content[:200]}`"
				))
