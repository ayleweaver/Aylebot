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
AUCTION_PUBLIC_NOTIFIER_CHANNEL_ID = 0
ROLE_NOTIFICATION_ID = {}
ROOM_STATUS_TAGS = {}
AUCTION_STATUS_TAGS = {}
ROOM_TYPE_TAGS = {}
EVENTS_TRIGGER: Dict = {}
ROOM_SELECT_DEFAULT_FREQUENCY_TIME = 0
ROOM_SELECT_DEFAULT_FREQUENCY_COUNT = 0
DB_NAME = "queue.db"
TELEMETRY_DB_NAME = "telemetry.db"
queue_connection = None
queue_cursor = None
telemetry_db_connection = None
telemetry_db_cursor = None

def setup(config_file: str):
	global BOT_TOKEN, FORUM_CHANNEL_ID, ROOM_STATUS_TAGS, ROOM_TYPE_TAGS, NOTIFICATION_CHANNEL_ID, AUCTION_CHANNEL_ID, AUCTION_STATUS_TAGS
	global ROLE_NOTIFICATION_ID
	global EVENTS_TRIGGER, ROOM_SELECT_DEFAULT_FREQUENCY_TIME, ROOM_SELECT_DEFAULT_FREQUENCY_COUNT, CURRENT_ENV, AUCTION_PUBLIC_NOTIFIER_CHANNEL_ID
	global DB_NAME, queue_connection, queue_cursor, telemetry_db_connection, telemetry_db_cursor

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
		ROLE_NOTIFICATION_ID = data['role_notification_id']
		AUCTION_PUBLIC_NOTIFIER_CHANNEL_ID = data['channel_id']['auction_public_notifier']
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
			TELEMETRY_DB_NAME = "telemetry_testing.db"
		queue_connection = sqlite3.connect(DB_NAME)
		telemetry_db_connection = sqlite3.connect(TELEMETRY_DB_NAME)
		queue_cursor = queue_connection.cursor()
		telemetry_db_cursor = telemetry_db_connection.cursor()

		# create table
		queue_cursor.execute("CREATE TABLE IF NOT EXISTS queue(thread_id, message_id, user_id, end_time, cc_user, is_reservation)")
		queue_cursor.execute("CREATE TABLE IF NOT EXISTS auction(thread_id, message_id, end_time, bid_increment, bid_current, bid_count, last_bid_user_id)")

		telemetry_db_cursor.execute("create table if not exists room_stats(thread_id, rent_count, extension_count, rent_total_time)")

		del data
