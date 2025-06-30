import traceback

import config

from dataclasses import dataclass
from datetime import datetime, timedelta
from discord import Interaction, Thread, Message, errors, ui
from discord.ext.commands import Bot

from logger import logger
from typing import List

@dataclass
class AuctionData:
	bidding_message: int
	bidding_announcement_message: int

def create_auction_history_table(thread_id: int) -> None:
	"""
	Initialize a table for auction history
	Args:
		thread_id (int): the thread id

	Returns:
		None
	"""
	if len(list(config.queue_cursor.execute(f"select tbl_name from sqlite_master where type='table' and tbl_name='auction_history_{thread_id}';").fetchall())) > 0:
		logger.info(f"Auction history existed for thread {thread_id}. Dropping this table.")
		config.queue_cursor.execute(f"drop table auction_history_{thread_id}")

	logger.info(f"Initializing table for thread {thread_id}")
	config.queue_cursor.execute(f"CREATE TABLE IF NOT EXISTS auction_history_{thread_id}(user_id, bid, current_bid, set_bid)")
	config.queue_connection.commit()

def get_auction_info(thread: Thread, columns: List=None) -> List:
	"""
	checking to see if this thread has an auction in it
	Args:
		thread (discord.Thread): a discord Thread object

	Returns:
		List - a list of threads containing auction information.
	"""

	thread_ids = config.queue_cursor.execute(f"""
							select {'*' if columns is None else 'auction.'+','.join(columns)}
							from auction
							join auction_info as b
							on auction.thread_id = b.thread_id
							where auction.thread_id = {thread.id}
						""").fetchall()
	if len(thread_ids) == 0:
		return []
	return thread_ids

def remove_auction(thread_id: int):
	"""
	remove auction information from database
	Args:
		thread_id (int): discord thread id

	Returns:

	"""

	# remove auction from master auction tables
	config.queue_cursor.execute(f"DELETE FROM auction WHERE thread_id = {thread_id}")
	config.queue_cursor.execute(f"DELETE FROM auction_info WHERE thread_id = {thread_id}")
	# remove history_table
	config.queue_cursor.execute(f"drop table auction_history_{thread_id}")
	config.queue_connection.commit()

async def auction_task(bot: Bot):
	"""
	background task for bot to run
	Args:
		bot ():

	Returns:

	"""

	# check auction if it ended
	auction_key_count = config.queue_cursor.execute("SELECT count(*) FROM auction").fetchone()[0]
	if auction_key_count > 0:
		res = config.queue_cursor.execute(f"SELECT * FROM auction WHERE end_time <= {int(datetime.now().timestamp())}")
		keys = res.fetchall()
		for k in keys:
			try:
				thread_id, end_time, bid_increment, bid_current, bid_count, last_bid_user_id = k
				_, auction_msg_info_id, message_id, announcement_msg_id = config.queue_cursor.execute(f"SELECT * FROM auction_info where thread_id = {thread_id}").fetchone()

				auction_announcement_chn = await bot.fetch_channel(config.AUCTION_PUBLIC_NOTIFIER_CHANNEL_ID)
				message: Message = await bot.get_channel(config.AUCTION_CHANNEL_ID).get_thread(thread_id).fetch_message(message_id)
				channel = await message.guild.fetch_channel(config.AUCTION_CHANNEL_ID)
				thread = await message.guild.fetch_channel(message.channel.id)

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

				# remove all of bot's messages in this thread
				logger.info("Removing bot messages about the auction")
				msgs = thread.history()
				async for m in msgs:
					if m.author.id == bot.user.id:
						await m.delete()

				if last_bid_user_id == -1:
					# no winner, notify me
					logger.info(
						f"Auction {thread_id} completed. "
						f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil]. "
						f"No Winner."
					)
					await bot.get_user(1082827074189930536).send(
						f"Auction {thread_id} completed.\n"
						f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil].\n"
						f"No Winner."
					)
				else:
					# notify winner
					winner_info = bot.get_user(last_bid_user_id)
					try:
						await winner_info.send(
							f"# :tada: __Congratulations!__ :tada:\n"
							f"## You are the winner of an auction in the Weaver's Nest!\n\n"
							f"The final bid was `{bid_current:,}` Gil\n\n"
							f"Please see the thread **<#{thread_id}>** in the Weaver's Nest **{channel.name} ** channel.\n"
							f"Please see reception in-game for your payment.\n"
							f"-# Your claim to your prize expires <t:{int((datetime.now() + timedelta(minutes=10)).timestamp())}:R>. If you do not accept within this timeframe, your prize will go to the next bidder."
						)
					except errors.Forbidden:
						# cannot dm user (usually permission)
						await thread.send(
							f"# :tada: __Congratulations <@{last_bid_user_id}>!__ :tada:\n"
							f"## You are the winner of an auction in the Weaver's Nest!\n\n"
							f"The final bid was `{bid_current:,}` Gil\n\n"
							f"Please see the thread **<#{thread_id}>** in the Weaver's Nest **{channel.name} ** channel.\n"
							f"Please see reception in-game for your payment.\n"
							f"-# Your claim to your prize expires <t:{int((datetime.now() + timedelta(minutes=10)).timestamp())}:R>. If you do not accept within this timeframe, your prize will go to the next bidder."
						)

					# notify me
					await bot.get_user(1082827074189930536).send(
						f"Auction {thread_id} completed.\n"
						f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil].\n"
						f"Winner: {winner_info.name} ({winner_info.global_name} | {last_bid_user_id})."
					)

					logger.info(
						f"Auction {thread_id} completed. "
						f"[{channel.name} {thread.name}] auction is finalized with [{bid_current:,} Gil]. "
						f"Winner: {bot.get_user(last_bid_user_id).name} ({last_bid_user_id})"
					)

				# remove auction record from master table
				logger.info("Removing record from master auction table")
				config.queue_cursor.execute(f"DELETE FROM auction WHERE thread_id = {thread_id}")
				config.queue_cursor.execute(f"DELETE FROM auction_info WHERE thread_id = {thread_id}")
				config.queue_connection.commit()

				# post some auction stats
				logger.info("Posting post-auction stats")
				await thread.send(
					"# This auction has ended!\n"
					f"## There was {bid_count} bid{'' if bid_count == 1 else 's'} made.\n"
					f"## The final bid was `{bid_current:,}` Gil!\n"
					f"The winner has been notified. Thank you for your participation!"
				)

				# edit announcement message
				msgs = auction_announcement_chn.history()
				announcement_msgs = [m async for m in msgs if m.id == announcement_msg_id]
				if len(announcement_msgs) == 0:
					await channel.send(
						"Fatal error has occurred. Current price message is not found.\n"
						"-# Paging <@1082827074189930536>"
					)
				await announcement_msgs[0].edit(
					content=f"## An auction has ended!\n"
					f"<#{thread.id}>. The final bid was`{bid_current:,}` Gil.\n"
					f"There was {bid_count} bids made."
				)

			except errors.NotFound as e:
				logger.error(f"queue_checker caught an exception: {type(e)} {e}")
				traceback.print_exc()