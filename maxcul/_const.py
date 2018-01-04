
# local constants
DEVICE_TYPES = {
    0: "Cube",
    1: "HeatingThermostat",
    2: "HeatingThermostatPlus",
    3: "WallMountedThermostat",
    4: "ShutterContact",
    5: "PushButton"
}
DEVICE_TYPES_BY_NAME = dict((v, k) for k, v in DEVICE_TYPES.items())

MODE_IDS = {
    0: "auto",
    1: "manual",
    2: "temporary",
    3: "boost",
}

MODE_AUTO = 'auto'
MODE_MANUAL = 'manual'
MODE_TEMPORARY = 'temporary'
MODE_BOOST = 'boost'

SHUTTER_STATES = {
    0: "close",
    2: "open",
}

DECALC_DAYS = {
    "Sat" : 0,
    "Sun" : 1,
    "Mon" : 2,
    "Tue" : 3,
    "Wed" : 4,
    "Thu" : 5,
    "Fri" : 6
}

BOOST_DURATION = {
    0 : 0,
    5 : 1,
    10: 2,
    15: 3,
    20: 4,
    25: 5,
    30: 6,
    60: 7
}

MIN_TEMPERATURE = 4.5
MAX_TEMPERATURE = 30.5

EVENT_THERMOSTAT_UPDATE = 'thermostat_update'
EVENT_DEVICE_PAIRED = 'device_paired'
EVENT_DEVICE_REPAIRED = 'device_repaired'

ATTR_DEVICE_ID = 'device_id'
ATTR_DESIRED_TEMPERATURE = 'desired_temperature'
ATTR_MEASURED_TEMPERATURE = 'measured_temperature'
ATTR_MODE = 'mode'
ATTR_BATTERY_LOW = 'battery_low'
