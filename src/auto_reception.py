import config

from datetime import datetime, timedelta
from discord import Message, User
from logger import logger
from icecream import ic
from typing import List

_queue_size = 0

class CheckInData:
	def __init__(self, thread_id:int, message: Message, user_id: int, end_time: int, cc_user_id: int=0):
		self.thread_id = thread_id
		self.message: Message = message
		self.user_id: int = user_id
		self.end_time: int = end_time
		self.cc_user_id: int = cc_user_id


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
	config.queue_connection.commit()

@log_reception
def check_in(data: CheckInData):
	global _queue_size
	_queue_size += 1

	config.queue_cursor.execute(f"""
		INSERT INTO queue (thread_id, message_id, user_id, end_time, cc_user)
		VALUES (?, ?, ?, ?, ?)
	""", (data.thread_id, data.message.id, data.user_id, data.end_time, data.cc_user_id))
	config.queue_connection.commit()

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