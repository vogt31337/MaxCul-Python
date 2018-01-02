import queue
import threading
import time
import logging
from serial import Serial

LOGGER = logging.getLogger(__name__)

class CULComThread(threading.Thread):
    """Low-level serial communication thread base"""

    def __init__(self, device_path, baudrate):
        super(CULComThread, self).__init__()
        self.send_queue = queue.Queue()
        self.read_queue = queue.Queue()
        self.device_path = device_path
        self.baudrate = baudrate
        self.pending_line = ""
        self.stop_requested = threading.Event()
        self.cul_version = ""
        self._pending_budget = 0
        self._pending_message = None

    def run(self):
        self._init_cul()
        while not self.stop_requested.isSet():
            # Send budget request if we don't know it
            if self._pending_budget == 0:
                self.request_budget()

            # Process pending received messages (if any)
            read_line = self._read_result()
            if read_line is not None:
                if read_line.startswith("21  "):
                    self._pending_budget = int(read_line[3:].strip()) * 10 or 1
                    LOGGER.info("Got pending budget: %sms" % self._pending_budget)
                else:
                    LOGGER.info("Got unhandled response from CUL: '%s'" % read_line)

            if self._pending_message is None and not self.send_queue.empty():
                LOGGER.debug("Fetching message from queue")
                self._pending_message = self.send_queue.get(True, 0.05)
                if self._pending_message is None:
                    LOGGER.debug("Failed fetching message due to thread lock, deferring")

            # send queued messages yet respecting send budget of 1%
            if self._pending_message:
                LOGGER.debug("Checking quota for outgoing message")
                if self._pending_budget > len(self._pending_message)*10:
                    LOGGER.debug("Queueing pre-fetched command %s" % self._pending_message)
                    self.send_command(self._pending_message)
                    self._pending_message = None
                else:
                    self._pending_budget = 0
                    LOGGER.debug("Not enough quota, re-check enforced")

            # give the system 200ms to do something else, we're embedded....
            time.sleep(0.2)

    def request_budget(self):
        self.send_command("X")
        for i in range(10):
            read_line = self._read_result()
            if read_line is not None:
                if read_line.startswith("21  "):
                    self._pending_budget = int(read_line[3:].strip()) * 10 or 1
                    LOGGER.info("Got pending budget message: %sms" % self._pending_budget)
                else:
                    LOGGER.info("Got unhandled response from CUL: '%s'" % read_line)
            if self._pending_budget > 0:
                LOGGER.debug("Finished fetching budget, having %sms now" % self._pending_budget)
                break
            time.sleep(0.05)

    def join(self, timeout=None):
        self.stop_requested.set()
        super(CULComThread, self).join(timeout)

    def _init_cul(self):
        """Ensure CUL reports reception strength and does not do FS messages"""

        self.com_port = Serial(self.device_path, self.baudrate)
        # was required for my nanoCUL
        time.sleep(2)
        LOGGER.debug("Initialized serial device")
        self._read_result()
        LOGGER.debug("Flushed read buffer")
        # get CUL FW version
        def _get_cul_ver():
            self.send_command("V")
            time.sleep(1)
            LOGGER.debug("currently %d bytes available for reading" % self.com_port.in_waiting)
            self.cul_version = self._read_result() or ""
        for i in range(10):
            _get_cul_ver()
            if self.cul_version:
                LOGGER.info("CUL reported version %s" % self.cul_version)
                break
            else:
                LOGGER.info("No version from CUL reported?")
        if not self.cul_version:
            LOGGER.info("No version from CUL reported. Closing and re-opening port")
            self.com_port.close()
            self.com_port = Serial(self.device_path, self.baudrate)
            for i in range(10):
                _get_cul_ver()
                if self.cul_version:
                    LOGGER.info("CUL reported version %s" % self.cul_version)
                else:
                    LOGGER.info("No version from CUL reported?")
            LOGGER.error("No version from CUL, cannot communicate")
            self.stop_requested.set()
            return

        # enable reporting of message strength
        self.send_command("X21")
        time.sleep(0.3)
        # receive Moritz messages
        self.send_command("Zr")
        time.sleep(0.3)
        # disable FHT mode by setting station to 0000
        self.send_command("T01")
        time.sleep(0.3)
        self._read_result()

    @property
    def has_send_budget(self):
        """Ask CUL if we have enough budget of the 1 percent rule left"""

        return self._pending_budget >= 2000

    def send_command(self, command):
        """Sends given command to CUL. Invalidates has_send_budget if command starts with Zs"""

        if command.startswith("Zs"):
            self._pending_budget = 0
        written = self.com_port.write((command + "\r\n").encode())
        LOGGER.debug("sent: %s, %d bytes written" % (command, written))

    def _read_result(self):
        """Reads data from port, if it's a Moritz message, forward directly, otherwise return to caller"""

        while self.com_port.in_waiting > 0 or len(self.pending_line) > 0:
            if self.com_port.in_waiting > 0:
                self.pending_line += self.com_port.read(self.com_port.in_waiting).decode("utf-8")
            if "\r\n" in self.pending_line:
                # remove newlines at the end
                (completed_line, _separator, self.pending_line) = self.pending_line.partition("\r\n")
                LOGGER.debug("received: %s" % completed_line)
                if completed_line.startswith("Z"):
                    self.read_queue.put(completed_line)
                else:
                    return completed_line
