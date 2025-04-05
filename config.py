import yaml
import sqlite3

from datetime import datetime
from icecream import ic
from logger import logger
from typing import Dict
from enum import IntEnum, auto

class ENVIRONMENT(IntEnum):
	LIVE = 0
	TESTING = 1

CURRENT_ENV = ENVIRONMENT.LIVE
BOT_TOKEN = ""
NOTIFICATION_CHANNEL_ID = 0
FORUM_CHANNEL_ID = 0
AUCTION_CHANNEL_ID = 0
ROOM_STATUS_TAGS = {}
AUCTION_STATUS_TAGS = {}
ROOM_TYPE_TAGS = {}
EVENTS_TRIGGER: Dict = {}
ROOM_SELECT_DEFAULT_FREQUENCY_TIME = 0
ROOM_SELECT_DEFAULT_FREQUENCY_COUNT = 0
DB_NAME = "queue.db"
queue_connection = None
queue_cursor = None

def setup(config_file: str):
	global BOT_TOKEN, FORUM_CHANNEL_ID, ROOM_STATUS_TAGS, ROOM_TYPE_TAGS, NOTIFICATION_CHANNEL_ID, AUCTION_CHANNEL_ID, AUCTION_STATUS_TAGS
	global EVENTS_TRIGGER, ROOM_SELECT_DEFAULT_FREQUENCY_TIME, ROOM_SELECT_DEFAULT_FREQUENCY_COUNT, CURRENT_ENV
	global DB_NAME, queue_connection, queue_cursor

	logger.info(f"Bot is using config file: {config_file}")
	with open(config_file) as f:
		data = yaml.safe_load(f)

		if "testing" in data:
			if data["testing"]:
				CURRENT_ENV = ENVIRONMENT.TESTING
			else:
				CURRENT_ENV = ENVIRONMENT.LIVE
		BOT_TOKEN = data['bot_token']
		NOTIFICATION_CHANNEL_ID = data['channel_id']['notifier']
		FORUM_CHANNEL_ID = data['channel_id']['room']
		AUCTION_CHANNEL_ID = data['channel_id']['auction']
		AUCTION_STATUS_TAGS = data['thread_status_tags']['auction']
		ROOM_STATUS_TAGS = data['thread_status_tags']['room']
		ROOM_TYPE_TAGS = data['thread_status_tags']['room_type']
		EVENTS_TRIGGER = data['triggers']
		ROOM_SELECT_DEFAULT_FREQUENCY_TIME = data['room_time_selection_frequency']
		ROOM_SELECT_DEFAULT_FREQUENCY_COUNT = data['room_time_selection_count']
		# adjust time to datatime and add triggered variable
		for events in EVENTS_TRIGGER:
			EVENTS_TRIGGER[events]['triggered'] = False
			EVENTS_TRIGGER[events]['time'] = datetime.strptime(EVENTS_TRIGGER[events]['time'], "%I:%M %p")

		assert len(ROOM_STATUS_TAGS) > 0, "No status tags, set your tag in config.yml"
		assert len(ROOM_TYPE_TAGS) > 0, "No type tags, set your tag in config.yml"
		assert FORUM_CHANNEL_ID, "No channel ID, set your channel ID in config.yml"

		# establishing database connection
		if CURRENT_ENV == ENVIRONMENT.TESTING:
			DB_NAME = "queue_testing.db"
		queue_connection = sqlite3.connect(DB_NAME)
		queue_cursor = queue_connection.cursor()

		# create table
		queue_cursor.execute("CREATE TABLE IF NOT EXISTS queue(thread_id, message_id, user_id, end_time, cc_user)")
		queue_cursor.execute("CREATE TABLE IF NOT EXISTS auction(thread_id, message_id, end_time, bid_increment, bid_current, bid_count, last_bid_user_id)")

		del data
