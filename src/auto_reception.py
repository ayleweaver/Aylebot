import config

from datetime import datetime, timedelta
from discord import Message, User, TextChannel, errors
from logger import logger
from icecream import ic
from typing import List

_queue_size = 0

class CheckInData:
	def __init__(self, thread_id:int, message: Message, user_id: int, duration: int, end_time: int, cc_user_id: int=None, is_reservation=False):
		self.thread_id = thread_id
		self.message: Message = message
		self.user_id: int = user_id
		self.duration = duration
		self.end_time: int = end_time
		self.cc_user_id: int = cc_user_id
		self.is_reservation = is_reservation


def log_reception(func):
	def inner(*args, **kwargs):
		status = func(*args, **kwargs)

		logger.info(f"Queue now has {_queue_size} item(s)")
		return status
	return inner

def get_thread_end_times(thread_id: int) -> List:
	"""
	returns the message id of this thread that contains the end time
	Args:
		thread_id (int): thread id

	Returns:
		List: containing the message id and the end time (posix time)
	"""
	# get the messages in this thread
	message_ids = config.queue_cursor.execute(f"""
		select message_id, end_time
		from queue
		where thread_id = {thread_id}
	""").fetchall()

	return message_ids

def is_room_occupied(thread_id: int) -> bool:
	"""
	Check to see if the room with the specified ID is listed in the queue's master table
	Args:
		thread_id (int): discord Thread ID

	Returns:
		bool
	"""
	return config.queue_cursor.execute(f"select exists(select 1 from queue where thread_id={thread_id} and is_reservation=0 limit 1)").fetchone()[0]

@log_reception
def extension(thread_id: int, duration: timedelta) -> None:
	"""
	Extends the end time of the room in question
	Args:
		thread_id (int): The id of the forum post
		duration (int): The duration of extension
	Returns:
		None
	"""
	# update row
	thread_data = get_thread_end_times(thread_id)
	assert(len(thread_data) == 1)

	old_message_id, old_end_time = thread_data[0]
	new_end_duration = round((datetime.fromtimestamp(old_end_time) + duration).timestamp())
	config.queue_cursor.execute(f"""
		update queue
		set 
			end_time = {new_end_duration}
		where thread_id = {thread_id}
	""")
	config.telemetry_db_cursor.execute(f"""
		update room_stats
		set
			extension_count = extension_count+1,
			rent_total_time = rent_total_time + {duration.total_seconds() / 3600}
		where thread_id = {thread_id}
	""")
	config.queue_connection.commit()
	config.telemetry_db_connection.commit()

@log_reception
def check_in(data: CheckInData):
	global _queue_size
	_queue_size += 1

	config.queue_cursor.execute(f"""
		INSERT INTO queue (thread_id, message_id, user_id, end_time, cc_user, is_reservation)
		VALUES (?, ?, ?, ?, ?, ?)
	""", (data.thread_id, data.message.id, data.user_id, data.end_time, data.cc_user_id, data.is_reservation))
	config.queue_connection.commit()

	# check telemetry entry if it is created
	if not data.is_reservation:
		row_check = config.telemetry_db_cursor.execute(f"select exists(select 1 from room_stats where thread_id={data.thread_id} limit 1)").fetchone()[0]
		if row_check:
			# entry exists, we update
			config.telemetry_db_cursor.execute(f"""
				update room_stats
				set
					rent_count = rent_count + 1,
					rent_total_time = rent_total_time + {data.duration / 3600}
				where thread_id = {data.thread_id}
			""")
		else:
			# no data exists, we insert
			config.telemetry_db_cursor.execute(f"""
				insert into room_stats(thread_id, rent_count, extension_count, rent_total_time)
				values (?, ?, ?, ?)
			""", (data.thread_id, 1, 0, data.duration / 3600))
		config.telemetry_db_connection.commit()

@log_reception
def check_out(key=0, msg_id=0):
	"""
	Removes check in data from queue by either message id or time

	If both arguments are provided, msg id will be checked first
	Args:
		key (int, optional): timestamp from the interaction's created_at
		msg_id (string, optional): message_id to reference

	Returns:
		list: list of msg id's removed
	"""
	global _queue_size
	_queue_size -= 1

	config.queue_cursor.execute(f"DELETE FROM queue WHERE end_time = {key} or message_id = {msg_id}")
	config.queue_connection.commit()

async def room_task(bot):
	key_count = config.queue_cursor.execute("SELECT count(*) FROM queue").fetchone()[0]
	if key_count > 0:
		res = config.queue_cursor.execute(f"SELECT * FROM queue WHERE end_time <= {int(datetime.now().timestamp())}")
		keys = res.fetchall()

		for k in keys:
			try:
				thread_id, message_id, user_id, end_time, cc_user, prereservation = k
				message: Message = await bot.get_channel(config.FORUM_CHANNEL_ID).get_thread(thread_id).fetch_message(message_id)
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
				check_out(key=end_time)

				# ping notification channel
				target_user_id: int = user_id
				target_channel: TextChannel = await message.guild.fetch_channel(config.NOTIFICATION_CHANNEL_ID)
				if not prereservation:
					# normal checkout message, reserved while room is occupied
					m = (f"<@{target_user_id}>\n" +
					     f"Room {message.channel.name} has been auto checked out." + (" This room has reserveration." if has_reservation else "") + "\n")

					if has_reservation:
						# set up pre-reservation
						reservation_duration = timedelta(minutes=config.ROOM_SELECT_DEFAULT_FREQUENCY_TIME * 2).total_seconds()
						msg = await thread.send(f"Reservation ends <t:{end_time + reservation_duration:.0f}:R>")
						check_in(
							CheckInData(
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
							channel.get_tag(config.ROOM_STATUS_TAGS['reserved']),
							reason="Autocheck out"
						)

						target_user: User = bot.get_user(user_id)
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
			except errors.NotFound as e:
				logger.error(f"queue_checker caught an exception: {type(e)} {e}")
