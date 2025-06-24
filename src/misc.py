import re

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
