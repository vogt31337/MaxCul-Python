# -*- coding: utf-8 -*-
"""
    maxcul.communication
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    There are two communication classes available which should run in their own thread.
    CULComThread performs low-level serial communication, CULMessageThread performs high-level
    communication and spawns a CULComThread for its low-level needs.

    Generally just use CULMessageThread unless you have a good reason not to.

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports
from datetime import datetime
import queue
import threading
import time

# environment imports
import logging

# custom imports
from maxcul.exceptions import MoritzError
from maxcul.messages import (
    MoritzMessage, MoritzError,
    PairPingMessage, PairPongMessage,
    TimeInformationMessage,
    SetTemperatureMessage,
    ThermostatStateMessage,
    AckMessage,
    ShutterContactStateMessage,
    ConfigValveMessage,
    SetGroupIdMessage,
    AddLinkPartnerMessage,
    WallThermostatStateMessage,
    WallThermostatControlMessage
)
from maxcul.io import CULComThread
from maxcul.const import *

# local constants
LOGGER = logging.getLogger(__name__)

# Hardcodings based on FHEM recommendations
CUBE_ID = 0x123456

class CULMessageThread(threading.Thread):
    """High level message processing"""

    def __init__(self, device_path = '/dev/ttyUSB0', baudrate = '38400', sender_id = CUBE_ID, callback = None, paired_devices = []):
        super(CULMessageThread, self).__init__()
        self.sender_id = CUBE_ID
        self.com_thread = CULComThread(device_path, baudrate)
        self.stop_requested = threading.Event()
        self._pairing_enabled = threading.Event()
        self._paired_devices = paired_devices
        self.callback = callback
        self._msg_count = 0

    def run(self):
        self.com_thread.start()
        while not self.stop_requested.is_set():
            self._receive_message()
            time.sleep(0.3)

    def stop(self, timeout=None):
        LOGGER.info("Stopping MAXCUL")
        self.com_thread.stop(timeout)
        self.stop_requested.set()
        self.join(timeout)

    def enable_pairing(self, duration=30):
        LOGGER.info("Enable pairing for {} seconds".format(duration))
        self._pairing_enabled.set()
        def clear_pair():
            self._pairing_enabled.clear()
        threading.Timer(duration, clear_pair).start()

    def set_temperature(self, receiver_id, temperature, mode):
        LOGGER.info("Setting temperature for {} to {} {}".format(receiver_id, temperature, mode))
        msg = SetTemperatureMessage(
            counter = self._next_counter(),
            sender_id = self.sender_id,
            receiver_id = receiver_id
        )
        payload = {
            'desired_temperature': float(temperature),
            'mode': mode,
        }
        self._send_message(msg, payload)

    def _next_counter(self):
        self._msg_count += 1
        return self._msg_count

    def _receive_message(self):
        try:
            received_msg = self.com_thread.read_queue.get(True, 0.05)
            message = MoritzMessage.decode_message(received_msg[:-2])
            signal_strength = int(received_msg[-2:], base=16)
            self._handle_message(message, signal_strength)
        except queue.Empty:
            pass
        except MoritzError as e:
            LOGGER.error("Message parsing failed, ignoring message '%s'. Reason: %s" % (received_msg, str(e)))

    def _send_message(self, msg, payload):
        try:
            raw_message = msg.encode_message(payload)
            LOGGER.debug("send type %s" % msg)
            LOGGER.debug("send raw line %s" % raw_message)
            self.com_thread.enqueue_command(raw_message)
        except MoritzError as e:
            LOGGER.error("Message sending failed, ignoring message '%s'. Reason: %s" % (msg, str(e)))

    def _send_ack(self, msg):
        ack_msg = msg.respond_with(AckMessage, counter = msg.counter, sender_id = self.sender_id)
        LOGGER.info("ack requested by 0x%X, responding" % msg.sender_id)
        self._send_message(ack_msg, "00")

    def _send_timeinformation(self, msg):
        resp_msg = msg.respond_with(TimeInformationMessage, counter = self._next_counter(), sender_id = self.sender_id)
        LOGGER.info("time information requested by 0x%X, responding" % msg.sender_id)
        self._send_message(resp_msg, datetime.now())

    def _send_pong(self, msg):
        resp_msg = msg.respond_with(PairPongMessage, counter = self._next_counter(), sender_id = self.sender_id)
        if self.com_thread.has_send_budget:
            self._send_message(resp_msg, {"devicetype": "Cube"})
            self._paired_devices.append(msg.sender_id)
            return True
        else:
            LOGGER.info("NOT responding to pair send budget is insufficient to be on time")
            return False

    def _handle_message(self, msg, signal_strenth):
        """Internal function to respond to incoming messages where appropriate"""
        if msg.receiver_id != 0 and msg.receiver_id != self.sender_id:
            # discard messages not addressed to us
            return

        LOGGER.debug("Received message {} ({})".format(msg, signal_strenth))
        if msg.decoded_payload:
            LOGGER.debug("Payload is {}".format(msg.decoded_payload))

        if isinstance(msg, PairPingMessage):
            LOGGER.info("Received pair request from {}".format(msg.sender_id))
            # Some peer wants to pair. Let's see...
            if msg.receiver_id == 0x0:
                # pairing after factory reset
                if not self._pairing_enabled.is_set():
                    LOGGER.info("Pairing disabled, not pairing to new device")
                    return
                if self._send_pong(msg):
                    self._call_callback(EVENT_DEVICE_PAIRED, { 'device_id': msg.sender_id })
            elif msg.receiver_id == self.sender_id:
                # pairing after battery replacement
                if self._send_pong(msg):
                    self._call_callback(EVENT_DEVICE_REPAIRED, { 'device_id': msg.sender_id })
            else:
                # pair to someone else after battery replacement, don't care
                LOGGER.info("pair after battery replacement sent to other device 0x%X, ignoring" % msg.receiver_id)
            return

        if msg.receiver_id == 0 and msg.sender_id not in self._paired_devices:
            # discard broadcast messages from devices we are not paired with
            return

        if isinstance(msg, TimeInformationMessage):
            if not msg.payload:
                # time information requested
                self._send_timeinformation(msg)

        elif isinstance(msg, ThermostatStateMessage):
            LOGGER.info("thermostat state updated for 0x%X" % msg.sender_id)
            self._send_ack(msg)
            self._propagate_thermostat_change(msg)

        elif isinstance(msg, AckMessage):
            if "state" in msg.decoded_payload and msg.decoded_payload["state"] == "ok":
                self._propagate_thermostat_change(msg)
                LOGGER.info("ack and thermostat state updated for 0x%X" % msg.sender_id)

        elif isinstance(msg, ShutterContactStateMessage) \
             or isinstance(msg, WallThermostatStateMessage) \
             or isinstance(msg, SetTemperatureMessage) \
             or isinstance(msg, WallThermostatControlMessage):
            self._send_ack(msg)

        else:
            LOGGER.warning("Unhandled Message of type %s, contains %s" % (msg.__class__.__name__, str(msg)))

    def _propagate_thermostat_change(self, msg):
        payload = msg.decoded_payload
        payload = {
            'device_id': msg.sender_id,
            'current_temperature': payload.get('measured_temperature'),
            'target_temperature': payload.get('desired_temperature'),
            'mode': payload.get('mode'),
            'battery_low': payload.get('battery_low')

        }
        self._call_callback(EVENT_THERMOSTAT_UPDATE, payload)

    def _call_callback(self, event, payload):
        if self.callback:
            try:
                self.callback(event, payload)
            except Exception as e:
                LOGGER.warn("Error while calling callback for thermostat update: {}".format(e))
