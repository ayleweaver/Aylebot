import traceback
import discord
import config, re

from datetime import datetime, timedelta
from discord import app_commands, Interaction, Client, TextChannel, ui, ButtonStyle
from discord.ext import commands
from icecream import ic
from logger import logger
from typing import List
from src.misc import number_abbreviation_parser, parse_duration
from src.auction import create_auction_history_table, get_auction_info

#####################################################################
# DISCORD VIEWS
#####################################################################

# Define a simple View that gives us a confirmation menu
class Confirm(ui.View):
	def __init__(self):
		super().__init__(timeout=None)
		self.value = None

	# When the confirm button is pressed, set the inner value to `True` and
	# stop the View from listening to more input.
	# We also send the user an ephemeral message that we're confirming their choice.
	@ui.button(label='Confirm', style=ButtonStyle.green)
	async def confirm(self, interaction: Interaction, button: ui.Button):
		await interaction.response.send_message("Confirmed. Removing entry from database.\n-# You don't need to do anything.", ephemeral=True, delete_after=5)
		self.value = True
		self.stop()

	# This one is similar to the confirmation button except sets the inner value to `False`
	@ui.button(label='Cancel', style=ButtonStyle.grey)
	async def cancel(self, interaction: Interaction, button: ui.Button):
		await interaction.response.send_message("Doing nothing. \n-# You don't need to do anything.", ephemeral=True, delete_after=5)
		self.value = False
		self.stop()

class CustomBidModel(discord.ui.Modal, title='Auction Bid'):
	bid_amount_input = discord.ui.TextInput(
		label='How much do you want to bid?',
		style=discord.TextStyle.short,
		placeholder="(e.g. 1m, \"500,000\", 300k)",
		required=True,
		max_length=12,
	)

	async def on_submit(self, interaction: discord.Interaction):
		thread = await interaction.guild.fetch_channel(interaction.channel_id)
		# checking to see if this thread has an auction in it
		thread_ids = config.queue_cursor.execute(f"""
				select thread_id, message_id, bid_increment, bid_current
				from auction
				where thread_id = {thread.id}
			""").fetchall()
		_, message_id, bid_increment, bid_current = thread_ids[0]

		if number_abbreviation_parser(self.bid_amount_input.value) > bid_current * 3:
			await interaction.response.send_message(f"You cannot bid more than 3 times the current bid!\nMaximum bid right now: `{bid_current*3:,}` Gil", ephemeral=True)
		else:
			await _place_bid(interaction, bid_amount=self.bid_amount_input.value)

	async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
		await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)
		logger.error(f"Exception when parsing custom bid amount. {type(error)}: {error}")


class BidView(ui.View):
	def __init__(self):
		super().__init__(timeout=None)

	# TODO: make view presist. See https://github.com/Rapptz/discord.py/blob/v2.5.2/examples/views/persistent.py
	@ui.button(label='Bid!', style=ButtonStyle.green, custom_id=f"persistent_button_bid")
	async def bid(self, interaction: discord.Interaction, button: discord.ui.Button):
		# await interaction.response.send_message("bidded!")
		await _place_bid(interaction, "")

	@ui.button(label="Custom Bid Amount", custom_id=f"persistent_button_custom_bid")
	async def custom_bid(self, interaction: discord.Interaction, button: discord.ui.Button):
		await interaction.response.send_modal(CustomBidModel())


#####################################################################
# HELPER FUNCTIONS
#####################################################################


async def _place_bid(interaction: Interaction, bid_amount: str=""):
	"""
	Place a bid in an active auction
	Args:
		interaction (discord.Interaction): A discord.Interaction object. Do not create your own. Must be passed in.
		bid_amount (str): Custom bid amount. Must be larger than the auction's increment bid and current bid combined

	Returns:

	"""
	thread = await interaction.guild.fetch_channel(interaction.channel_id)
	# checking to see if this thread has an auction in it
	auction_data = get_auction_info(thread)
	if not auction_data:
		await interaction.response.send_message(
			"There is no auction in this thread. Please navigate to an active auction.",
			ephemeral=True
		)
		return

	# parsing bid
	_, _, msg_id, _, _, bid_increment, bid_current, bid_count, last_bid_user_id = auction_data[0]
	set_fix_value = False

	# checking to see if user was the last person who place a bid
	if last_bid_user_id == interaction.user.id:
		await interaction.response.send_message(
			"You are the current bidder. You cannot double bid!",
			ephemeral=True
		)
		return

	# user made custom bid
	if len(bid_amount) > 0:
		try:
			# try to parse bid
			if "," in bid_amount:
				bid_amount = bid_amount.replace(",", "")

			bid_amount = number_abbreviation_parser(bid_amount)

			if bid_amount <= bid_current:
				# check to see if bid is larger than current bid
				await interaction.response.send_message(
					f"This amount must be larger than the current bid!\n"
					f"You bid: `{bid_amount:,}`\n"
					f"Current bid: `{bid_current:,}`",
					ephemeral=True
				)
				return
			elif bid_amount - bid_current < bid_increment:
				# check to see if bid is larger than increment bid
				await interaction.response.send_message(
					f"This amount must be larger than the increment bid!\n"
					f"You bid: `{bid_amount:,}`\n"
					f"Current bid: `{bid_current:,}`\n"
					f"--------------------------\n"
					f"Difference: `{bid_amount - bid_current:,}`\n"
					f"Incremental bid: `{bid_increment:,}`",
					ephemeral=True
				)
				return

			# user's custom bid is valid
			set_fix_value = True
			await interaction.response.send_message(
				f"You have raise the bid to `{bid_amount:,}`!",
				ephemeral=True
			)
		except ValueError:
			# can't parse
			await interaction.response.send_message(
				f"I am having trouble understanding the value `{bid_amount}`. Please try again.",
				ephemeral=True
			)
			return
	else:
		if bid_count == 0:
			# user made the initial bid, set their bid as the current bid
			bid_amount = bid_current
			set_fix_value = True
			await interaction.response.send_message(
				f"You have made a bid for `{bid_current:,}`!",
				ephemeral=True
			)
		else:
			# user made normal bid
			bid_amount = bid_increment
			await interaction.response.send_message(
				f"You have made a bid for `{bid_current + bid_amount:,}`!",
				ephemeral=True
			)
	new_bid_value = bid_amount if set_fix_value else bid_current + bid_amount
	# update master record
	config.queue_cursor.execute(f"""
						update auction
						set 
							bid_current = {new_bid_value},
							last_bid_user_id = {interaction.user.id},
							bid_count = bid_count + 1
						where thread_id = {thread.id}
					""")
	# add to bid history
	config.queue_cursor.execute(f"""
						INSERT INTO auction_history_{thread.id}(user_id, bid, current_bid, set_bid)
						VALUES (?, ?, ?, ?)
					""", (interaction.user.id, bid_amount, new_bid_value, set_fix_value))
	config.queue_connection.commit()

	# log bid
	logger.info(
		f"[{interaction.channel.name}] has a bid for "
		f"[{bid_amount:,} Gil] "
		f"by [{interaction.user.global_name} ({interaction.user.name}, {interaction.user.id})]. "
		f"Current total is {new_bid_value:,}."
	)

	# edit price message
	msgs = thread.history()
	msg_to_edit = [m async for m in msgs if m.id == msg_id]
	if len(msg_to_edit) == 0:
		await interaction.channel.send(
			"Fatal error has occurred. Current price message is not found.\n"
			"-# Paging <@1082827074189930536>"
		)
	await msg_to_edit[0].edit(
		content=f"Current bid: `{new_bid_value:,}` Gil\n"
		        f"{bid_count+1} Bid{'' if bid_count+1 == 1 else 's'}"
	)

# table columns:
# thread_id, message_id, end_time, bid_increment, bid_current, last_bid_user_id


#####################################################################
# DISCORD COMMANDS
#####################################################################

class Auction(commands.GroupCog):
	def __init__(self, bot):
		self.bot: Client = bot

	@app_commands.command(name="begin", description="Begin auction in this thread")
	@app_commands.checks.has_permissions(administrator=True)
	@app_commands.describe(
		duration="How long does this auction last. (Example input: 1d3h)",
		starting_bid="The initial bid",
		bid_increment="The incremental bid",
		test_bid="Test bid, does not notify auction role"
	)
	async def begin(self, interaction: Interaction, duration: str, starting_bid: str, bid_increment: str, test_bid:bool=False):
		channel = await interaction.guild.fetch_channel(config.AUCTION_CHANNEL_ID)
		thread = await interaction.guild.fetch_channel(interaction.channel_id)

		if config.AUCTION_STATUS_TAGS['ready'] not in [t.id for t in thread.applied_tags]:
			# needs ready tag to get able to start
			tag = channel.get_tag(config.AUCTION_STATUS_TAGS['ready'])
			await interaction.response.send_message(
				f"This thread needs the [**{tag.emoji} {tag.name}**] tag to begin auction. Please review it before marking it as ready and initializing.",
				ephemeral=True
			)
			return
		await thread.override_tags(
			channel.get_tag(config.AUCTION_STATUS_TAGS['in_progress'])
		)

		# checking to see if this thread has an auction in it
		if get_auction_info(thread):
			await interaction.response.send_message(
				"There is an active auction going on. Please wait until the auction ends.",
				ephemeral=True
			)
			return

		# parse bid values
		starting_bid = number_abbreviation_parser(starting_bid)
		bid_increment = number_abbreviation_parser(bid_increment)

		# parse duration and set up times
		auction_duration, auction_endtime_timestamp = parse_duration(duration)

		view = BidView()
		# send messages
		await interaction.response.send_message("Request Processing", delete_after=5)
		auction_info_msg = await interaction.channel.send(
			"# This auction has begun\n"
			f"## You may bid until <t:{auction_endtime_timestamp}:f>\n"
			f"## Auction closes <t:{auction_endtime_timestamp}:R>\n"
			f"Bid increments: `{bid_increment:,}` Gil"
		)

		# send notification
		chn = await self.bot.fetch_channel(config.AUCTION_PUBLIC_NOTIFIER_CHANNEL_ID)
		notification_msg_content = (
			f"## A new auction as started!\n"
			f"<#{thread.id}>. Starting at `{starting_bid:,}` Gil.\n"
			f"Ends on <t:{auction_endtime_timestamp}:f> (<t:{auction_endtime_timestamp}:R>)\n"
		)

		if test_bid:
			notification_msg_content += "-# This is a test bid, please ignore."
		else:
			notification_msg_content += f"-# <@&{config.ROLE_NOTIFICATION_ID['auction']}>"

		notification_msg = await chn.send(
			notification_msg_content
		)

		msg = await interaction.channel.send(
			f"Starting bid: `{starting_bid:,}` Gil",
			view=view
		)

		# add entry to table
		config.queue_cursor.execute(f"""
			INSERT INTO auction (thread_id, auction_info_msg_id, message_id, notification_id, end_time, bid_increment, bid_current, bid_count, last_bid_user_id)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		""", (thread.id, auction_info_msg.id, msg.id, notification_msg.id, auction_endtime_timestamp, bid_increment, starting_bid, 0, -1))
		config.queue_connection.commit()

		# initialize history table
		create_auction_history_table(thread.id)

		# log
		logger.info(
			f"[{interaction.channel.name}] has an auction started for "
			f"[{str(auction_duration)}] until "
			f"[{datetime.fromtimestamp(auction_endtime_timestamp).astimezone().strftime('%I:%M:%S %p %z %Z')}] set "
			f"by [{interaction.user.global_name} ({interaction.user.name})]"
		)

	@app_commands.command(name="cancel", description="Cancel this auction")
	@app_commands.checks.has_permissions(administrator=True)
	async def cancel(self, interaction: Interaction, cancel_reason: str):
		channel = await interaction.guild.fetch_channel(config.AUCTION_CHANNEL_ID)
		thread = await interaction.guild.fetch_channel(interaction.channel_id)
		# checking to see if this thread has an auction in it
		thread_ids = get_auction_info(thread)
		if not thread_ids:
			await interaction.response.send_message(
				"There is no auction in this thread. Please navigate to an active auction.",
				ephemeral=True
			)
			return

		delete_confirmation = Confirm()

		await interaction.response.send_message(
			"# __:warning: You are able to cancel and this auction! Do you want to continue? :warning:__\n"
			f"-# This message will delete <t:{int((datetime.now() + timedelta(seconds=15)).timestamp())}:R>",
			ephemeral=True,
			delete_after=15,
			view=delete_confirmation
		)
		await delete_confirmation.wait()

		if delete_confirmation.value is None:
			logger.warning("delete_confirmation has timed out.")
		elif delete_confirmation.value:
			# remove auction from master auction table
			config.queue_cursor.execute(f"DELETE FROM auction WHERE thread_id = {thread.id}")
			# remove history_table
			config.queue_cursor.execute(f"drop table auction_history_{thread.id}")
			config.queue_connection.commit()

			# remove tags
			await thread.override_tags()

			# remove all of bot's messages in this thread
			msgs = thread.history()
			async for m in msgs:
				if m.author.id == self.bot.user.id:
					await m.delete()
			await interaction.channel.send(
				"This auction has been cancelled.\nReason: " + ("No reason given" if not cancel_reason else cancel_reason)
			)
		else:
			# do nothing
			pass

	@app_commands.command(name="extend", description="Extends the duration of this auction")
	@app_commands.checks.has_permissions(administrator=True)
	async def extend(self, interaction: Interaction, duration: str):
		channel = await interaction.guild.fetch_channel(config.AUCTION_CHANNEL_ID)
		thread = await interaction.guild.fetch_channel(interaction.channel_id)

		# check if auction is actually active in backend
		auction_data = get_auction_info(thread)
		if not auction_data:
			logger.warning(f"Auction {thread.id} does not exists in database.")

		# check to see if auction is active in discord
		if config.AUCTION_STATUS_TAGS['in_progress'] not in [t.id for t in thread.applied_tags]:
			# needs in progress tag to get able to extend
			logger.info(
				f"Auction extension attempted by [{interaction.user.global_name} ({interaction.user.name})], but auction is not in progressed, "
			)

			tag = channel.get_tag(config.AUCTION_STATUS_TAGS['in_progress'])
			await interaction.response.send_message(
				f"This thread needs the [**{tag.emoji} {tag.name}**] tag to extend auction. Please review it before extending it.",
				ephemeral=True
			)
			return

		thread_id, auction_info_msg_id, msg_id, notification_id, end_time, bid_increment, current_bid, bid_count, _ = auction_data[0]

		extend_duration, auction_new_timestamp = parse_duration(duration, datetime.fromtimestamp(end_time))

		# modifying message
		history = interaction.channel.history()
		msg = [m async for m in history if m.id == auction_info_msg_id][0]
		await msg.edit(content=
			"# This auction has begun\n"
			f"## You may bid until <t:{auction_new_timestamp}:f>\n"
			f"## Auction closes <t:{auction_new_timestamp}:R>\n"
			f"Bid increments: `{bid_increment:,}` Gil"
		)

		# modifying announcement message
		auction_announcement_chn = await interaction.guild.fetch_channel(config.AUCTION_PUBLIC_NOTIFIER_CHANNEL_ID)
		history = auction_announcement_chn.history()
		msg = [m async for m in history if m.id == notification_id][0]
		await msg.edit(content=
			f"## An auction has been extended!\n"
			f"<#{thread.id}>. Current at `{current_bid:,}` Gil.\n"
			f"Ends on <t:{auction_new_timestamp}:f> (<t:{auction_new_timestamp}:R>)\n"
			f"-# <@&{config.ROLE_NOTIFICATION_ID['auction']}"
        )

		# updating the auction master table
		config.queue_cursor.execute(f"""
			update auction
			set
				end_time = {auction_new_timestamp}
			where thread_id = {thread_id}
		""")


		logger.info(
			f"[{interaction.channel.name}] has an auction extended for "
			f"[{str(extend_duration)}] until "
			f"[{datetime.fromtimestamp(auction_new_timestamp).astimezone().strftime('%I:%M:%S %p %z %Z')}] set "
			f"by [{interaction.user.global_name} ({interaction.user.name})]"
		)

		await interaction.response.send_message(
			f"Auction has been extended by {str(extend_duration)} (until <t:{auction_new_timestamp}:F>).",
			ephemeral=True
		)


	@app_commands.command(name="participants", description="Get all of the participants in bidding order of this auction")
	@app_commands.checks.has_permissions(administrator=True)
	async def participants(self, interaction: Interaction):
		thread = await interaction.guild.fetch_channel(interaction.channel_id)

		_participants = config.queue_cursor.execute(f"select user_id, current_bid from auction_history_{thread.id} order by current_bid desc limit 10;").fetchall()
		if len(_participants) > 0:
			m = ""
			for participant_data in _participants:
				user_id, current_bid = participant_data
				m += f"<@{user_id}> ({user_id}): {current_bid}\n"


			await interaction.response.send_message(
				m,
				ephemeral=True
			)
		else:
			await interaction.response.send_message(
				"There are no participants in this auction.",
				ephemeral=True
			)

	@app_commands.command(name="faq", description="Display FAQ for this Aylebot feature.")
	async def faq(self, interaction: Interaction):
		await interaction.response.send_message(
			"# AyleBot Auction FAQ\n"
			f"1. How do I participate?\n"
			f"  - Please contact the venue's owner if you would like to be auctioned off.\n"
			f"2. How do I bid?\n"
			f"  - To place a bid, press the green \"Bid!\" button to raise the current bid by the increment bid.\n"
			f"  - To place a bid larger than the current bid, press the \"Custom Bid Amount\" to raise the current bid to a desired amount.\n"
			f"    - Note: you will need to place a bid that is at least the current bid and incremental bid combined.\n"
			f"    - Example: using **/auction bid 3500** when the current bid is 3,000 and the incremental bid is 300 will increase the current bid to 3,500.\n"
			f"3. What is the maximum amount of custom bid I can place at once?\n"
			f"  - You can place up to 3 times the current bid (i.e. if the current bid is 3.5m, your custom bid cannot be higher than 10.5m)\n"
			f"4. What happens when the time ends?\n"
			f"  - If you are the winner, Aylebot will DM you notifying that you are the winner. Please follow the instructino that it provide to then proceed."
			f"5. What happens if I waited too long to redeem my auction prize?\n"
			f"  - After 10 minutes, the auction prize will go to the next person that bids before you.\n",
			ephemeral=True
		)