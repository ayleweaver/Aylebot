import config, discord

from datetime import datetime, timedelta
from discord import app_commands, Interaction
from discord.ext import commands
from icecream import ic
from logger import logger
from typing import List

from src.auto_reception import check_out, check_in, extension, get_thread_end_times, CheckInData

async def auto_complete_time(interaction: Interaction, current: str) -> List[app_commands.Choice[timedelta]]:
	time_choices = [
		[
			datetime.strptime(str(timedelta(minutes=config.ROOM_SELECT_DEFAULT_FREQUENCY_TIME*i)), "%H:%M:%S").strftime("%#Hh %#Mm"),
			i
		] for i in range(1, config.ROOM_SELECT_DEFAULT_FREQUENCY_COUNT+1)
	]
	return [app_commands.Choice(name=choice_name, value=choice_value) for choice_name, choice_value in time_choices]

class Room(commands.Cog):
	def __init__(self, client, forum_id, room_status_tag_id, room_type_tag_id):
		self.client = client
		self.forum_id = forum_id
		self.room_status_tag_id = room_status_tag_id
		self.room_type_tag_id = room_type_tag_id

	@app_commands.command(name="occupied", description="Close this room and mark it as occupied")
	@app_commands.describe(
		time="How long does room rented for",
		cc_user="Also ping this user when room is expires"
	)
	@app_commands.autocomplete(
		time=auto_complete_time
	)
	async def occupied(self, interaction: Interaction, time: int, cc_user: discord.User=None):
		# note: add tags to  thread requires "Send Messages in Posts" (also allow to add messages in that thread)
		# note: delete messages in thread requires "Manage Messages"
		channel = await interaction.guild.fetch_channel(self.forum_id)
		thread = await interaction.guild.fetch_channel(interaction.channel_id)
		room_type = list(set(list(self.room_type_tag_id.values())) & set(thread._applied_tags))

		duration = timedelta(minutes=config.ROOM_SELECT_DEFAULT_FREQUENCY_TIME*time)
		start_time: datetime = interaction.created_at
		end_time: datetime = start_time + duration
		try:
			# add occupied tag and availble time
			# await thread.remove_tags(channel.get_tag(self.room_status_tag_id['available']), reason="Guest Check In")
			# await thread.add_tags(channel.get_tag(self.room_status_tag_id['occupied']), reason="Guest Check In")
			await thread.override_tags(
				channel.get_tag(room_type[0]),
				channel.get_tag(self.room_status_tag_id['occupied']),
				reason="Guest Check In"
			)
			await interaction.response.send_message("Request Processing", delete_after=1, ephemeral=True)

			msg = await interaction.channel.send(f"Available <t:{end_time.timestamp():.0f}:R>")
			check_in(
				CheckInData(
					thread.id,
					msg,
					interaction.user.id,
					duration.total_seconds(),
					int(end_time.timestamp()),
					cc_user_id=cc_user.id if cc_user is not None else None
				)
			)

			logger.info(
				f"[{interaction.channel.name}] is occupied for "
				f"[{datetime.strptime(str(duration), '%H:%M:%S').strftime('%#Hh %#Mm')}] until "
				f"[{end_time.astimezone().strftime('%I:%M:%S %p %z %Z')}] set "
				f"by [{interaction.user.global_name} ({interaction.user.name})]"
			)
		except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
			logger.error(f"Exception {type(e)}: {e}")

	@app_commands.command(name="reserve", description="Reserve this room for an hour.")
	async def reserve(self, interaction: Interaction):
		# note: add tags to  thread requires "Send Messages in Posts" (also allow to add messages in that thread)
		# note: delete messages in thread requires "Manage Messages"
		channel = await interaction.guild.fetch_channel(self.forum_id)
		thread = await interaction.guild.fetch_channel(interaction.channel_id)
		room_type = list(set(list(self.room_type_tag_id.values())) & set(thread._applied_tags))

		duration = timedelta(minutes=config.ROOM_SELECT_DEFAULT_FREQUENCY_TIME * 2)
		start_time: datetime = interaction.created_at
		end_time: datetime = start_time + duration

		# check if this room is already occupied
		room_occupied = config.queue_cursor.execute(f"select exists(select 1 from queue where thread_id={thread.id} limit 1)").fetchone()[0]

		if not room_occupied:
			try:
				# set reseve tag and availble time
				await thread.override_tags(
					channel.get_tag(room_type[0]),
					channel.get_tag(self.room_status_tag_id['reserved']),
					reason="Room reservation"
				)
				await interaction.response.send_message("Request Processing", delete_after=1, ephemeral=True)

				msg = await interaction.channel.send(f"Reservation ends <t:{end_time.timestamp():.0f}:R>")
				check_in(
					CheckInData(
						thread.id,
						msg,
						interaction.user.id,
						duration.total_seconds(),
						int(end_time.timestamp()),
						is_reservation=True
					)
				)

				logger.info(
					f"[{interaction.channel.name}] is reserved for "
					f"[{datetime.strptime(str(duration), '%H:%M:%S').strftime('%#Hh %#Mm')}] until "
					f"[{end_time.astimezone().strftime('%I:%M:%S %p %z %Z')}] set "
					f"by [{interaction.user.global_name} ({interaction.user.name})]"
				)
			except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
				logger.error(f"Exception {type(e)}: {e}")
		else:
			# if this room is already occupied, add reservation tag
			await thread.add_tags(
				channel.get_tag(self.room_status_tag_id['reserved']),
				reason="Room reservation"
			)
			await interaction.response.send_message(
				"Request Processing",
				delete_after=1,
				ephemeral=True
			)

			logger.info(
				f"[{interaction.channel.name}] is reserved for the next set of patrons "
				f"by [{interaction.user.global_name} ({interaction.user.name})]"
			)

	@app_commands.command(name="extend", description="Extend the duration of this room")
	@app_commands.describe(
		time="How many more hours in this room",
	)
	@app_commands.autocomplete(
		time=auto_complete_time
	)
	async def extend(self, interaction: Interaction, time: int):
		# note: add tags to  thread requires "Send Messages in Posts" (also allow to add messages in that thread)
		# note: delete messages in thread requires "Manage Messages"
		channel = await interaction.guild.fetch_channel(self.forum_id)
		thread = await interaction.guild.fetch_channel(interaction.channel_id)
		room_type = list(set(list(self.room_type_tag_id.values())) & set(thread._applied_tags))

		# set time stuff
		duration = timedelta(minutes=config.ROOM_SELECT_DEFAULT_FREQUENCY_TIME*time)
		start_time: datetime = interaction.created_at
		end_time: datetime = start_time + duration
		if not config.ROOM_STATUS_TAGS['occupied'] in thread._applied_tags:
			# no occupied tag, send error
			await interaction.response.send_message(
				"This room is not currently occupied!\n"
				"-# Please `/occupied` the room before `/extend`",
				ephemeral=True
			)
		else:
			# has occupied tag, extend time

			# grab old time
			msg_id = 0
			old_end_time = get_thread_end_times(thread.id)
			if len(old_end_time) > 1:
				logger.warning(f"Multiple messages are found with thread id {thread.id}")
			elif len(old_end_time) == 1:
				msg_id = old_end_time[0][0]
				end_time = datetime.fromtimestamp(old_end_time[0][1]) + duration
			else:
				logger.error(f"Fatal: No messages are found with thread id {thread.id}")
				await interaction.response.send_message("A fatal error has occurred. Paging <@1082827074189930536>")

			try:
				await interaction.response.send_message("Request Processing", delete_after=1, ephemeral=True)

				history = interaction.channel.history()
				msg = [m async for m in history if m.id == msg_id][0]
				extension(thread.id, duration)

				await msg.edit(content=f"Available <t:{end_time.timestamp():.0f}:R>")

				logger.info(
					f"[{interaction.channel.name}] has extension for "
					f"[{datetime.strptime(str(duration), '%H:%M:%S').strftime('%#Hh %#Mm')}] until "
					f"[{end_time.astimezone().strftime('%I:%M:%S %p %z %Z')}] set "
					f"by [{interaction.user.global_name} ({interaction.user.name})]"
				)

			except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
				logger.error(f"Exception {type(e)}: {e}")

	@app_commands.command(name="clear", description="Clear all status of this room")
	async def clear(self, interaction: Interaction):

		channel = await interaction.guild.fetch_channel(self.forum_id)
		thread = interaction.channel

		logger.info(f"[{interaction.channel.name}] status cleared by {interaction.user.global_name} ({interaction.user.name})")

		room_type = list(set(list(self.room_type_tag_id.values())) & set(thread._applied_tags))
		await thread.override_tags(
			channel.get_tag(room_type[0]),
			channel.get_tag(self.room_status_tag_id['available']),
			reason="Guest Check In"
		)
		msg = thread.history()
		msg_to_delete = [m async for m in msg if m.author.id == self.client.user.id]
		await thread.delete_messages(msg_to_delete)

		for m in msg_to_delete:
			check_out(msg_id=m.id)

		await interaction.response.send_message("Done\n-# This messsage will auto delete in 5s", delete_after=5, ephemeral=True)