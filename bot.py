#!/bin/python3
import asyncio, discord, argparse
import logging
import traceback

import config

from cogs import *
from cogs.admin import trigger_event
from cogs.auction import BidView
from datetime import datetime, timedelta
from discord import Message, ui
from discord.ext import commands, tasks
from icecream import ic
from logger import logger

bot_intents = discord.Intents(
	members=True,
	messages=True,
	guilds=True,
	typing=True,
	message_content=True,
)

class Bot(commands.Bot):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		# TODO: add loop exception
		# self.queue_checker.add_exception_type(AttributeError)

	async def setup_hook(self) -> None:
		active_auctions = config.queue_cursor.execute(f"""
				select thread_id, message_id, bid_increment, bid_current
				from auction
			""").fetchall()

		for _, msg_id, _, _ in active_auctions:
			self.add_view(BidView())

		self.queue_checker.start()
		await self.tree.sync()

	@tasks.loop(seconds=10)
	async def queue_checker(self):
		# check check-in data
		# remove all check in data after time expired
		key_count = config.queue_cursor.execute("SELECT count(*) FROM queue").fetchone()[0]
		if key_count > 0:
			res = config.queue_cursor.execute(f"SELECT * FROM queue WHERE end_time <= {int(datetime.now().timestamp())}")
			keys = res.fetchall()

			for k in keys:
				try:
					thread_id, message_id, user_id, end_time, cc_user, prereservation = k
					message: Message = await self.get_channel(config.FORUM_CHANNEL_ID).get_thread(thread_id).fetch_message(message_id)
					channel = await message.guild.fetch_channel(config.FORUM_CHANNEL_ID)
					thread = await message.guild.fetch_channel(message.channel.id)

					await message.delete()

					has_reservation = config.ROOM_STATUS_TAGS['reserved'] in thread._applied_tags

					room_type = list(set(list(config.ROOM_TYPE_TAGS.values())) & set(thread._applied_tags))
					await thread.override_tags(
						channel.get_tag(room_type[0]),
						channel.get_tag(config.ROOM_STATUS_TAGS['available']),
						reason="Autocheck out"
					)
					auto_reception.check_out(key=end_time)

					# ping notification channel
					target_user_id: int = user_id
					target_channel: discord.TextChannel = await message.guild.fetch_channel(config.NOTIFICATION_CHANNEL_ID)
					if not prereservation:
						# normal checkout message, reserved while room is occupied
						m = (f"<@{target_user_id}>\n"+
							f"Room {message.channel.name} has been auto checked out." + (" This room has reserveration." if has_reservation else "")+"\n")

						if has_reservation:
							# set up pre-reservation
							reservation_duration = timedelta(minutes=config.ROOM_SELECT_DEFAULT_FREQUENCY_TIME * 2).total_seconds()
							msg = await thread.send(f"Reservation ends <t:{end_time + reservation_duration:.0f}:R>")
							auto_reception.check_in(
								auto_reception.CheckInData(
									thread.id,
									msg,
									target_user_id,
									reservation_duration,
									int(end_time + reservation_duration),
									is_reservation=True
								)
							)
							await thread.override_tags(
								channel.get_tag(room_type[0]),
								channel.get_tag(config.ROOM_STATUS_TAGS['available']),
								channel.get_tag(config.ROOM_STATUS_TAGS['reserved']),
								reason="Autocheck out"
							)

							target_user: discord.User = self.get_user(user_id)
							logger.info(
								f"[{message.channel.name}] is reserved for the next set of patrons "
								f"by [{target_user.global_name} ({target_user.name})]"
							)
					else:
						# pre reservation message
						m = (f"<@{target_user_id}>\n"
						     f"Room {message.channel.name}'s resevation has expired.")


					if cc_user is not None:
						m += f"-# Also CCing <@{cc_user}>"

					await target_channel.send(m)
				except discord.errors.NotFound as e:
					logging.error(f"queue_checker caught an exception: {type(e)} {e}")

		# check auction if it ended
		auction_key_count = config.queue_cursor.execute("SELECT count(*) FROM auction").fetchone()[0]
		if auction_key_count > 0:
			res = config.queue_cursor.execute(f"SELECT * FROM auction WHERE end_time <= {int(datetime.now().timestamp())}")
			keys = res.fetchall()
			for k in keys:
				try:
					thread_id, message_id, end_time, bid_increment, bid_current, bid_count, last_bid_user_id = k

					message: Message = await self.get_channel(config.AUCTION_CHANNEL_ID).get_thread(thread_id).fetch_message(message_id)
					channel = await message.guild.fetch_channel(config.AUCTION_CHANNEL_ID)
					thread = await message.guild.fetch_channel(message.channel.id)

					if last_bid_user_id == -1:
						# no winner, notify me
						logger.info(
							f"Auction {thread_id} completed. "
							f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil]. "
							f"No Winner."
						)
						await self.get_user(1082827074189930536).send(
							f"Auction {thread_id} completed.\n"
							f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil].\n"
							f"No Winner."
						)
					else:
						# notify winner
						winner_info = self.get_user(last_bid_user_id)
						await winner_info.send(
							f"# :tada: __Congratulations!__ :tada:\n"
							f"## You are the winner of an auction in the Weaver's Nest!\n\n"
							f"The final bid was `{bid_current:,}` Gil\n\n"
							f"Please see the thread **{thread.name}** in the Weaver's Nest **{channel.name} ** channel.\n"
							f"Please see reception in-game for your payment.\n"
							f"-# Your claim to your prize expires <t:{int((datetime.now() + timedelta(minutes=10)).timestamp())}:R>. If you do not accept within this timeframe, your prize will go to the next bidder."
						)

						# notify me
						await self.get_user(1082827074189930536).send(
							f"Auction {thread_id} completed.\n"
							f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil].\n"
							f"Winner: {winner_info.name} ({winner_info.global_name} | {last_bid_user_id})."
						)

						logger.info(
							f"Auction {thread_id} completed. "
							f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil]. "
							f"Winner: {self.get_user(last_bid_user_id).name} ({last_bid_user_id})"
						)

					# remove tags
					logger.info("Overriding tags to archive")
					await thread.override_tags(
						channel.get_tag(config.AUCTION_STATUS_TAGS['archived'])
					)

					# disable buttons
					logger.info("Disabling buttons")
					view = ui.View.from_message(message)
					components = view.children
					for component in components:
						component.disabled = True

					await message.edit(
						view=view
					)

					# remove auction record from master table
					logger.info("Removing record from master auction table")
					config.queue_cursor.execute(f"DELETE FROM auction WHERE thread_id = {thread_id}")
					config.queue_connection.commit()


					# remove all of bot's messages in this thread
					logger.info("Removing bot messages about the auction")
					msgs = thread.history()
					async for m in msgs:
						if m.author.id == self.user.id:
							await m.delete()

					# post some auction stats
					logger.info("Posting post-auction stats")
					await thread.send(
						"# This auction has ended!\n"
						f"## There was {bid_count} bid{'' if bid_count == 1 else 's'} made.\n"
						f"## The final bid was `{bid_current:,}` Gil!\n"
						f"The winner has been notified. Thank you for your participation!"
					)
				except discord.errors.NotFound as e:
					logging.error(f"queue_checker caught an exception: {type(e)} {e}")
					traceback.print_exc()

		# event trigger checker
		time_now: datetime = datetime.now()
		for event in config.EVENTS_TRIGGER:
			if not config.EVENTS_TRIGGER[event]['triggered']:

				# hardcoded special condition for skipping
				if event in ["open", "close", "last_call"] and datetime.now().weekday() not in [5, 6]:
					# logger.info(f"event is part of [open, close, last_call] and it is not the weekend, skipping")
					continue

				event_time: datetime = config.EVENTS_TRIGGER[event]['time']
				if time_now.hour == event_time.hour and time_now.minute == event_time.minute:
					await trigger_event(self, event)
					config.EVENTS_TRIGGER[event]['triggered'] = True
			else:
				# resets trigger at 1 am
				if time_now.hour == 1 and time_now.minute == 0:
					config.EVENTS_TRIGGER[event]['triggered'] = False

	@queue_checker.before_loop
	async def queue_checker_before(self):
		await self.wait_until_ready()

bot = Bot(
	command_prefix=commands.when_mentioned_or("!"),
	intents=bot_intents,
	help_command=None
)

@bot.event
async def on_ready():
	logger.info(f"Current environment: {config.CURRENT_ENV.name}")
	logger.info("Ready")

@bot.event
async def on_message(message: discord.Message):
	if message.author.id != bot.user.id:
		if message.content == f"<@{bot.user.id}>":
			logger.info("Bot being pinged")
			await message.channel.send("Hm? You called?")


async def main():
	# load some stuff
	await bot.add_cog(Room(bot, config.FORUM_CHANNEL_ID, config.ROOM_STATUS_TAGS, config.ROOM_TYPE_TAGS))
	await bot.add_cog(Check(bot))
	await bot.add_cog(Misc(bot))
	await bot.add_cog(Auction(bot))


if __name__ == '__main__':

	parser = argparse.ArgumentParser()
	parser.add_argument("--config", required=True)

	args = parser.parse_args()

	config.setup(config_file=args.config)
	from src import auto_reception

	asyncio.run(main())
	bot.run(config.BOT_TOKEN)

	config.queue_connection.commit()
	config.queue_connection.close()
