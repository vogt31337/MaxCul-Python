# -*- coding: utf-8 -*-
"""
    maxcul.messages
    ~~~~~~~~~~~~~~~~~~~~~~~

    Definition of known messages, based on IDs from FHEM plugin

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports
from datetime import datetime
import struct

# environment imports

# custom imports
from maxcul.exceptions import (
    MoritzError, LengthNotMatchingError,
    MissingPayloadParameterError, UnknownMessageError
)

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


class MoritzMessage(object):
    """Represents (de)coded message as seen on Moritz Wire"""

    def __init__(self, counter=0, flag=0, sender_id=0, receiver_id=0, group_id=0, payload={}):
        self.counter = counter
        self.flag = flag
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.group_id = group_id
        self.payload = payload

    @property
    def decoded_payload(self):
        raise NotImplementedError()

    @property
    def is_broadcast(self):
        return self.receiver_id == 0

    @staticmethod
    def decode_message(input_string):
        """Decodes given message and returns content in matching message class"""

        if input_string.startswith("Zs"):
            # outgoing messages can be parsed too, just cut the Z off as it doesn't matter
            input_string = input_string[1:]

        # Split MAX message
        length = int(input_string[1:3], base=16)
        counter = int(input_string[3:5], base=16)
        flag = int(input_string[5:7], base=16)
        msgtype = int(input_string[7:9], base=16)
        sender_id = int(input_string[9:15], base=16)
        receiver_id = int(input_string[15:21], base=16)
        group_id = int(input_string[21:23], base=16)

        # Length: strlen(input_string) / 2 as HEX encoding, +3 for Z and length count
        if (len(input_string) - 3) != length * 2:
            # For some reason there are two methods... and I've seen both with culfw 1.67...
            # Some say the additional character(s) are some kind of CRC, currently investigating.
            if (len(input_string) - 5) == length * 2:
                input_string = input_string[:-2]
            else:
                raise LengthNotMatchingError(
                    "Message length %i not matching indicated length %i" % ((len(input_string) - 3) / 2, length))

        payload = input_string[23:]

        try:
            message_class = MORITZ_MESSAGE_IDS[msgtype]
        except KeyError:
            raise UnknownMessageError("Unknown message with id %x found" % msgtype)

        message = message_class()
        message.counter = counter
        message.flag = flag
        message.group_id = group_id
        message.sender_id = sender_id
        message.receiver_id = receiver_id
        message.payload = payload

        return message

    def encode_message(self, payload={}):
        """Prepare message to be sent on wire"""

        msg_ids = dict((v, k) for k, v in MORITZ_MESSAGE_IDS.items())
        msg_id = msg_ids[self.__class__]

        message = ""
        if hasattr(self, 'encode_payload'):
            self.payload = self.encode_payload(payload)
        if hasattr(self, 'encode_flag'):
            self.flag = self.encode_flag()
        for (var, length) in (
                (self.counter, 2), (self.flag, 2), (msg_id, 2), (self.sender_id, 6), (self.receiver_id, 6),
                (self.group_id, 2)):
            content = "%X".upper() % var
            message += content.zfill(length)
        if self.payload:
            message += self.payload
        length = "%X".upper() % int(len(message) / 2)
        message = "Zs" + length.zfill(2) + message
        return message

    def __repr__(self):
        return "<%s counter:%x flag:%x sender:%x receiver:%x group:%x payload:%s>" % (
            self.__class__.__name__, self.counter, self.flag, self.sender_id, self.receiver_id, self.group_id,
            self.payload
        )


class PairPingMessage(MoritzMessage):
    """Thermostats send this request on long boost keypress"""

    @property
    def decoded_payload(self):
        firmware_version, device_type, selftest_result = struct.unpack(">bBB", bytearray.fromhex(self.payload[:6]))
        device_serial = bytearray.fromhex(self.payload[6:]).decode()
        result = {
            'firmware_version': "V%i.%i" % (firmware_version / 0x10, firmware_version % 0x10),
            'device_type': DEVICE_TYPES[device_type],
            'selftest_result': selftest_result,
            'device_serial': device_serial,
            'pairmode': 'pair' if self.is_broadcast else 're-pair'
        }
        return result


class PairPongMessage(MoritzMessage):
    """Awaited after PairPingMessage is sent by component"""

    @property
    def decoded_payload(self):
        return {'devicetype': DEVICE_TYPES[int(self.payload)]}

    def encode_payload(self, payload):
        return str(DEVICE_TYPES_BY_NAME[payload['devicetype']]).zfill(2)


class AckMessage(MoritzMessage):
    """Last command received and acknowledged.
	   Occasionally if the communication is ongoing, this might get lost.
	   So don't rely on it but check state afterwards instead"""

    @property
    def decoded_payload(self):
        result = {}
        if self.payload.startswith("01"):
            result["state"] = "ok"
        elif self.payload.startswith("81"):
            result["state"] = "invalid_command"
        elif self.payload.startswith("00"):
            result["state"] = "ignore"
        if len(self.payload) == 8:
            # FIXME: temporarily accepting the fact that we only handle Thermostat results
            result.update(ThermostatStateMessage.decode_status(self.payload[2:]))
        return result

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload=None):
        return payload


class TimeInformationMessage(MoritzMessage):
    """Current time is either requested or encoded. Request simply is empty payload"""

    @property
    def decoded_payload(self):
        (years_since_2000, day, hour, month_minute, month_sec) = struct.unpack(">BBBBB",
                                                                              bytearray.fromhex(self.payload[:12]))
        return datetime(
            year=years_since_2000 + 2000,
            minute=month_minute & 0x3F,
            month=((month_minute & 0xC0) >> 4) | ((month_sec & 0xC0) >> 6),
            day=day,
            hour=hour & 0x3F,
            second=month_sec & 0x3F
        )

    def encode_flag(self):
        return 0x0A if not self.payload else 0x04

    def encode_payload(self, payload=None):
        # may contain empty payload to ask for timeinformation
        if payload is None:
            return ""
        encoded_payload = str("%X" % (payload.year - 2000)).zfill(2)
        encoded_payload += str("%X" % payload.day).zfill(2)
        encoded_payload += str("%X" % payload.hour).zfill(2)
        encoded_payload += str("%X" % (payload.minute | ((payload.month & 0x0C) << 4))).zfill(2)
        encoded_payload += str("%X" % (payload.second | ((payload.month & 0x03) << 6))).zfill(2)
        return encoded_payload


class ConfigWeekProfileMessage(MoritzMessage):
    pass


class ConfigTemperaturesMessage(MoritzMessage):
    """Sets temperatur config"""

    @property
    def decoded_payload(self):
        pass

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload):
        if "comfort_Temperature" not in payload:
            raise MissingPayloadParameterError("Missing comfort_Temperature in payload")
        if "eco_Temperature" not in payload:
            raise MissingPayloadParameterError("Missing eco_Temperature in payload")
        if "max_Temperature" not in payload:
            raise MissingPayloadParameterError("Missing max_Temperature in payload")
        if "min_Temperature" not in payload:
            raise MissingPayloadParameterError("Missing min_Temperature in payload")
        if "measurement_Offset" not in payload:
            raise MissingPayloadParameterError("Missing measurement_Offset in payload")
        if "window_Open_Temperatur" not in payload:
            raise MissingPayloadParameterError("Missing window_Open_Temperatur in payload")
        if "window_Open_Duration" not in payload:
            raise MissingPayloadParameterError("Missing window_Open_Duration in payload")

        comfort_Temperature = "%0.2X" % int(payload['comfort_Temperature']*2)
        eco_Temperature = "%0.2X" % int(payload['eco_Temperature']*2)
        max_Temperature = "%0.2X" % int(payload['max_Temperature']*2)
        min_Temperature = "%0.2X" % int(payload['min_Temperature']*2)
        measurement_Offset = "%0.2X" % int((payload['measurement_Offset'] + 3.5)*2)
        window_Open_Temperatur = "%0.2X" % int(payload['window_Open_Temperatur']*2)
        window_Open_Duration = "%0.2X" % int(payload['window_Open_Duration']/5)

        content = comfort_Temperature + eco_Temperature + max_Temperature + min_Temperature + measurement_Offset + window_Open_Temperatur +window_Open_Duration
        return content



class ConfigValveMessage(MoritzMessage):
    """Sets valve config"""

    @property
    def decoded_payload(self):
        pass

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload):
        if "boost_duration" not in payload:
            raise MissingPayloadParameterError("Missing boost duration in payload")
        if "boost_valve_position" not in payload:
            raise MissingPayloadParameterError("Missing boost valve position in payload")
        if "decalc_day" not in payload:
            raise MissingPayloadParameterError("Missing decalc day in payload")
        if "decalc_hour" not in payload:
            raise MissingPayloadParameterError("Missing decalc hour in payload")
        if "max_valve_position" not in payload:
            raise MissingPayloadParameterError("Missing max valve position in payload")
        if "valve_offset" not in payload:
            raise MissingPayloadParameterError("Missing valve offset in payload")

        boost = "%0.2X" % ((BOOST_DURATION[payload["boost_duration"]] << 5) | int(payload["boost_valve_position"]/5))
        decalc = "%0.2X" % ((DECALC_DAYS[payload["decalc_day"]] << 5) | payload["decalc_hour"])
        max_valve_position = "%0.2X" % int(payload["max_valve_position"]*255/100)
        valve_offset = "%0.2X" % int(payload["valve_offset"]*255/100)
        content = boost + decalc + max_valve_position + valve_offset
        return content


class AddLinkPartnerMessage(MoritzMessage):

    @property
    def decoded_payload(self):
        pass

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload):
        if "assocDevice" not in payload:
            raise MissingPayloadParameterError("Missing assocDevice in payload")
        if "assocDeviceType" not in payload:
            raise MissingPayloadParameterError("Missing assocDeviceType in payload")

        assocDevice = "%0.6X" % int(payload["assocDevice"])
        assocDeviceType = "%0.2X" % list(DEVICE_TYPES.keys())[list(DEVICE_TYPES.values()).index(payload["assocDeviceType"])]
        return assocDevice + assocDeviceType

class RemoveLinkPartnerMessage(MoritzMessage):

    @property
    def decoded_payload(self):
        pass

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload):
        if "assocDevice" not in payload:
            raise MissingPayloadParameterError("Missing assocDevice in payload")
        if "assocDeviceType" not in payload:
            raise MissingPayloadParameterError("Missing assocDeviceType in payload")

        assocDevice = payload["assocDevice"]
        assocDeviceType = "%0.2X" % DEVICE_TYPES[payload["assocDeviceType"]]
        return assocDevice + assocDeviceType


class SetGroupIdMessage(MoritzMessage):

    @property
    def decoded_payload(self):
        pass

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload):
        if "group_id" not in payload:
            raise MissingPayloadParameterError("Missing group id in payload")

        groupId = "%0.2X" % payload["group_id"]
        return groupId



class RemoveGroupIdMessage(MoritzMessage):

    @property
    def decoded_payload(self):
        pass

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload):
        overrideGroupId = "00"
        return overrideGroupId



class ShutterContactStateMessage(MoritzMessage):
    """Non-reculary sent by Thermostats to report when valve was moved or command received."""

    @staticmethod
    def decode_status(payload):
        status_bits = bin(int(payload, 16))[2:].zfill(8)
        state = int(status_bits[6:], 2)
        unkbits = int(status_bits[2:6], 2)
        rferror = int(status_bits[1], 2)
        battery_low = int(status_bits[0], 2)
        result = {
            "state": SHUTTER_STATES[state],
            "unkbits": unkbits,
            "rferror": bool(rferror),
            "battery_low": bool(battery_low)
        }
        return result

    @property
    def decoded_payload(self):
        result = ShutterContactStateMessage.decode_status(self.payload)
        return result

class SetTemperatureMessage(MoritzMessage):
    """Sets temperature for manual mode as well as mode switch between manual, auto and boost"""

    @property
    def decoded_payload(self):
        payload = struct.unpack(">B", bytearray.fromhex(self.payload[0:4]))
        return {
            'desired_temperature': ((payload[0] & 0x3F) / 2.0),
            'mode': MODE_IDS[payload[0] >> 6]
        }

    def encode_flag(self):
        return 0x4 if self.group_id else 0x0

    def encode_payload(self, payload):
        if "desired_temperature" not in payload:
            raise MissingPayloadParameterError("Missing desired_temperature in payload")
        if "mode" not in payload:
            raise MissingPayloadParameterError("Missing mode in payload")

        if payload['desired_temperature'] > 30.5:
            desired_temperature = 30.5  # "ON"
        elif payload['desired_temperature'] < 4.5:
            desired_temperature = 4.5  # "OFF"
        else:
            # always round to nearest 0.5 first
            desired_temperature = round(payload['desired_temperature'] * 2) / 2.0
        int_temperature = int(desired_temperature * 2)

        modes = dict((v, k) for (k, v) in MODE_IDS.items())
        mode = modes[payload['mode']]

        # TODO: you can add a until time for chort changes
        # from fhem
        # $until = sprintf("%06x",MAX_DateTime2Internal($args[2]." ".$args[3]));
        # $payload .= $until if(defined($until));
        content = "%X".upper() % ((mode << 6) | int_temperature)
        return content.zfill(2)


class WallThermostatControlMessage(MoritzMessage):

    @staticmethod
    def decode_status(payload):
        rawTempratures = bin(int(payload, 16))[2:].zfill(16)

        result = {
            "desired_temperature": int(rawTempratures[1:8], 2)/2,
            "temperature": ((int(rawTempratures[0], 2) << 8) + int(rawTempratures[8:], 2))/10
        }
        return result

    @property
    def decoded_payload(self):
        result = WallThermostatControlMessage.decode_status(self.payload)
        return result


class SetComfortTemperatureMessage(MoritzMessage):
    pass


class SetEcoTemperatureMessage(MoritzMessage):
    pass


class PushButtonStateMessage(MoritzMessage):

    @property
    def decoded_payload(self):
        #TODO: No plan, what to do with the two bits in the middle.
        status_bits = bin(int(self.payload[0], 16))[2:].zfill(3)
        state = int(self.payload[3], 2)
        langateway = int(status_bits[2], 2)
        rferror = int(status_bits[0], 2)
        battery_low = int(status_bits[1], 2)
        return {
            "state": bool(state),
            "rferror": bool(rferror),
            "battery_low": bool(battery_low),
            "langateway": bool(langateway)
        }


class ThermostatStateMessage(MoritzMessage):
    """Non-reculary sent by Thermostats to report when valve was moved or command received."""

    @staticmethod
    def decode_status(payload):
        status_bits, valve_position, desired_temperature = struct.unpack(">bBB", bytearray.fromhex(payload[0:6]))
        mode = status_bits & 0x3
        dstsetting = status_bits & 0x04
        langateway = status_bits & 0x08
        status_bits = status_bits >> 9
        is_locked = status_bits & 0x1
        rferror = status_bits & 0x2
        battery_low = status_bits & 0x4
        desired_temperature = (desired_temperature & 0x7F) / 2.0
        result = {
            "mode": MODE_IDS[mode],
            "dstsetting": bool(dstsetting),
            "langateway": bool(langateway),
            "is_locked": bool(is_locked),
            "rferror": bool(rferror),
            "battery_low": bool(battery_low),
            "desired_temperature": desired_temperature,
            "valve_position": valve_position,
        }
        return result

    @property
    def decoded_payload(self):
        result = ThermostatStateMessage.decode_status(self.payload)
        if len(self.payload) > 6:
            pending_payload = bytearray.fromhex(self.payload[6:])
            if len(pending_payload) == 3:
                # TODO handle date string
                pass
            elif len(pending_payload) == 2 and result['mode'] != 'temporary':
                result["measured_temperature"] = (((pending_payload[0] & 0x1) << 8) + pending_payload[1]) / 10.0
            else:
                # unknown....
                pass
        return result


class WallThermostatStateMessage(MoritzMessage):
    """Non-reculary sent by Thermostats to report when valve was moved or command received."""


    @staticmethod
    def decode_status(payload):
        status_bits = bin(int(payload[:2], 16))[2:].zfill(8)
        mode = int(status_bits[:2], 2)
        dstsetting = int(status_bits[2:3], 2)
        langateway = int(status_bits[3:4], 2)
        is_locked = int(status_bits[4:5], 2)
        rferror = int(status_bits[5:6], 2)
        battery_low = int(status_bits[6:7], 2)
        display_actual_temperature = bool(int(payload[2:4], 16))
        desired_temperature_raw = bin(int(payload[4:6], 16))[2:].zfill(8)
        desired_temperature = int(desired_temperature_raw[1:8], 2)/2
        heater_temperature = ""

        null1 = False
        if len(payload) > 6:
            null1 = payload[6:8]

        if len(payload) > 8:
            heater_temperature = payload[8:10]

        null2 = False
        if len(payload) > 10:
            null2 = payload[10:12]

        if len(payload) > 12:
            temperature = ((int(desired_temperature_raw[0], 2) << 8) + int(payload[12:], 16)) / 10

        until_str = ""
        if null1 and null2:
            until_str = parseDateTime(null1, heater_temperature, null2)
        else:
            temperature = int(heater_temperature, 16)/10

        result = {
            "mode": MODE_IDS[mode],
            "dstsetting": bool(dstsetting),
            "langateway": bool(langateway),
            "is_locked": bool(is_locked),
            "rferror": bool(rferror),
            "battery_low": bool(battery_low),
            "desired_temperature": desired_temperature,
            "display_actual_temperature": display_actual_temperature,
            "temperature": temperature,
            "until_str": until_str
        }
        return result

    @property
    def decoded_payload(self):
        result = WallThermostatStateMessage.decode_status(self.payload)
        return result


def parseDateTime(byte1, byte2, byte3):
    day = int(byte1, 16) & 0x1F
    month = ((int(byte1, 16) & 0xE0) >> 4) | (int(byte2, 16) >> 7)
    year = int(byte2, 16) & 0x3F
    time = int(byte3, 16) & 0x3F
    if time%2:
        time = int(time/2) + ':30'
    else:
        time = int(time/2) + ":00"

    return {
        "day": day,
        "month": month,
        "year": year,
        "time": time
    }


class SetDisplayActualTemperatureMessage(MoritzMessage):
    pass


class WakeUpMessage(MoritzMessage):
    pass


class ResetMessage(MoritzMessage):
    """Perform a factory reset on given device"""

    pass


# Define at bottom so we can use the class types right away
# Based on FHEM CUL_MAX module
MORITZ_MESSAGE_IDS = {
    0x00: PairPingMessage,
    0x01: PairPongMessage,
    0x02: AckMessage,
    0x03: TimeInformationMessage,

    0x10: ConfigWeekProfileMessage,
    0x11: ConfigTemperaturesMessage,
    0x12: ConfigValveMessage,

    0x20: AddLinkPartnerMessage,
    0x21: RemoveLinkPartnerMessage,
    0x22: SetGroupIdMessage,
    0x23: RemoveGroupIdMessage,

    0x30: ShutterContactStateMessage,

    0x40: SetTemperatureMessage,
    0x42: WallThermostatControlMessage,
    0x43: SetComfortTemperatureMessage,
    0x44: SetEcoTemperatureMessage,

    0x50: PushButtonStateMessage,

    0x60: ThermostatStateMessage,

    0x70: WallThermostatStateMessage,

    0x82: SetDisplayActualTemperatureMessage,

    0xF1: WakeUpMessage,
    0xF0: ResetMessage,
}
