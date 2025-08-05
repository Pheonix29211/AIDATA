from .browser import *
from .helpers import *
from .exceptions import *
from .const import *
from enum import Enum

class Interval(Enum):
    INTERVAL_1_MINUTE = '1'
    INTERVAL_5_MINUTE = '5'
    INTERVAL_15_MINUTE = '15'
    INTERVAL_1_HOUR = '60'
    INTERVAL_1_DAY = '1D'

class TvDatafeed:
    def __init__(self, username=None, password=None):
        pass  # Dummy constructor
