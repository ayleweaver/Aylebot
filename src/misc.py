import re
import logger
from datetime import datetime, timedelta

def number_abbreviation_parser(value: str):
	regex = re.compile(
		r'((?P<millions>\d+?\.?\d*?)m)?'
		r'((?P<thousands>\d+?\.?\d*?)k)?'
		r'(?P<ones>\d*\.?\d*)?'
	)
	# ?((\d+?\.\d*?)k)?(\d*\.\d*?)
	try:
		match = regex.match(value)
		group_dict = match.groupdict()
		group_dict = {k: float(v) if v else 0 for k, v in group_dict.items()}

		return int((group_dict['millions'] * 1000000) + (group_dict['thousands'] * 1000) + (group_dict['ones']))
	except ValueError:
		logger.warn(f"number abbreviation parser cannot parse input value {value}")
		return None

def parse_duration(duration: str, current_time: datetime=None):
	"""
	parse a duration to timedelta and timestamp from now to duration
	Args:
		duration (str): a human-readable duration (e.g. 1d, 2h, 300s)
		current_time (datetime, optional): a datetime object of the desired time (defaults to datetime.now())
	Returns:
		tuple - timedelta of duration and timestamp of current_time + duration
	"""
	# parse duration and set up times
	regex = re.compile(r'((?P<days>\d+?)d)?((?P<hours>\d+?)hr?)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?')
	match = regex.match(duration)
	duration_dict = match.groupdict()
	duration_dict = {k: int(v) if v is not None else 0 for k, v in duration_dict.items()}

	d = timedelta(**duration_dict)
	timestamp = int(((datetime.now() if current_time is None else current_time) + d).timestamp())

	return d, timestamp