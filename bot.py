#!/bin/python3
import asyncio, discord, argparse
import logging
import traceback

import config

from cogs import *
from cogs.admin import trigger_event
from cogs.auction import BidView
from datetime import datetime
from discord.ext import commands, tasks
from logger import logger
from src.auction import auction_task
from src.auto_reception import room_task

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
				select auction_info.message_id
				from auction
				join auction_info where auction.thread_id = auction_info.thread_id;
			""").fetchall()

		for message_id in active_auctions:
			self.add_view(BidView())

		self.queue_checker.start()
		await self.tree.sync()

	@tasks.loop(seconds=10)
	async def queue_checker(self):
		# check check-in data
		# remove all check in data after time expired

		await room_task(self)
		await auction_task(self)

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
