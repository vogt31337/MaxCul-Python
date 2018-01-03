# -*- coding: utf-8 -*-
"""
    maxcul
    ~~~~~~~~~~~~~~

    Implementation of moritz home automation protocol

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports

from maxcul.communication import MaxConnection
from maxcul.const import (
    # Events
    EVENT_DEVICE_PAIRED,
    EVENT_DEVICE_REPAIRED,
    EVENT_THERMOSTAT_UPDATE,
    # Thermostat modes
    MODE_AUTO, MODE_BOOST, MODE_MANUAL, MODE_TEMPORARY
)

# environment imports

# custom imports

# local constants
__version__ = "0.1.0"
