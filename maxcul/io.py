import queue
from collections import deque
import threading
import time
import logging
from serial import Serial

LOGGER = logging.getLogger(__name__)

MAX_QUEUED_COMMANDS = 10
READLINE_TIMEOUT = 0.5

COMMAND_REQUEST_BUDGET = 'X'

class CULComThread(threading.Thread):
    """Low-level serial communication thread base"""

    def __init__(self, device_path, baudrate):
        super().__init__()
        self.read_queue = queue.Queue()
        self._send_queue = deque([], MAX_QUEUED_COMMANDS)
        self._device_path = device_path
        self._baudrate = baudrate
        self._stop_requested = threading.Event()
        self._cul_version = ""
        self._remaining_budget = 0

    @property
    def cul_version(self):
        return self._cul_version

    @property
    def has_send_budget(self):
        """Ask CUL if we have enough budget of the 1 percent rule left"""
        return self._remaining_budget >= 2000

    def enqueue_command(self, command):
        self._send_queue.appendleft(command)

    def stop(self, timeout=None):
        self._stop_requested.set()
        self.join(timeout)

    def run(self):
        self._init_cul()
        while not self._stop_requested.isSet():
            self._loop()

    def _loop(self):
        if self._remaining_budget == 0:
            self._writeline(COMMAND_REQUEST_BUDGET)
        self._receive_message()
        self._send_pending_message()
        # give the system 200ms to do something else, we're embedded....
        time.sleep(0.2)

    def _receive_message(self):
        # Process pending received messages (if any)
        line = self._readline()
        if line is not None:
            if line.startswith("21  "):
                self._remaining_budget = int(line[3:].strip()) * 10 or 1
                LOGGER.info("Got pending budget: %sms" % self._remaining_budget)
            if line.startswith("Z"):
                self.read_queue.put(line)
            else:
                LOGGER.info("Got unhandled response from CUL: '%s'" % line)

    def _send_pending_message(self):
        try:
            pending_message = self._send_queue.pop()
            if self._remaining_budget > len(pending_message) * 10:
                self._writeline(pending_message)
            else:
                self._send_queue.append(pending_message)
                self._writeline(COMMAND_REQUEST_BUDGET)
        except IndexError:
            pass

    def _init_cul(self):
        for i in range(10):
            self._open_serial_device()
            if self._com_port is not None:
                break

        if self._com_port is None: 
            LOGGER.error("No version from CUL, cannot communicate")
            self._stop_requested.set()

    def _open_serial_device(self):
        self._com_port = Serial(self._device_path, self._baudrate, timeout=READLINE_TIMEOUT)
        # was required for my nanoCUL
        time.sleep(2)
        # get CUL FW version
        for i in range(10):
            self._writeline("V")
            time.sleep(1)
            self._cul_version = self._readline() or None
            if self._cul_version is not None:
                LOGGER.info("CUL reported version %s" % self._cul_version)
                break
            else:
                LOGGER.info("No version from CUL reported?")
        if self._cul_version is None:
            self._com_port.close()
            self._com_port = None
            return
        # enable reporting of message strength
        self._writeline("X21")
        time.sleep(0.3)
        # receive Moritz messages
        self._writeline("Zr")
        time.sleep(0.3)
        # disable FHT mode by setting station to 0000
        self._writeline("T01")
        time.sleep(0.3)

    def _writeline(self, command):
        """Sends given command to CUL. Invalidates has_send_budget if command starts with Zs"""
        if command.startswith("Zs"):
            self._remaining_budget = 0
        self._com_port.write((command + "\r\n").encode())

    def _readline(self):
        line = self._com_port.readline()
        if line is not None:
            line = line.decode('utf-8')[:-2]
        return line
