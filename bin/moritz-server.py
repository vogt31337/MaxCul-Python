# -*- coding: utf-8 -*-
"""
    moritz-server
    ~~~~~~~~~~~~~

    Sample HTTP Service providing current states of thermostats as well as command control interface to them

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports
from datetime import datetime
import queue
import json
from json import encoder

# environment imports
from flask import Flask, request, url_for
from flask_sqlalchemy import SQLAlchemy

# custom imports
from moritzprotocol.communication import CULMessageThread, CUBE_ID
from moritzprotocol.messages import SetTemperatureMessage, ConfigValveMessage, SetGroupIdMessage, ConfigTemperaturesMessage, AddLinkPartnerMessage, TimeInformationMessage
from moritzprotocol.signals import device_pair_accepted, device_pair_request, thermostatstate_received

# local constantsfrom datetime import datetime
encoder.FLOAT_REPR = lambda o: format(o, '.2f')

#
# Environment Setup
#
class JSONWithDateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///moritz-server.db'
db = SQLAlchemy(app)

command_queue = queue.Queue()

#
# Models
#
class Devices(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer)
    serial = db.Column(db.String(32))
    firmware_version = db.Column(db.String(32), nullable=True)
    name = db.Column(db.String(64))
    paired = db.Column(db.Boolean, default=False)
    device_type = db.Column(db.String(32))

    def __init__(self, sender_id, serial, device_type):
        self.sender_id = sender_id
        self.serial = serial
        self.name = serial
        self.device_type = device_type

    def __repr__(self):
        return "<%s sender_id=%s name=%s>" % (self.__class__.__name__, self.sender_id, self.name)


class ThermostatState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    thermostat_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    thermostat = db.relationship('Devices', backref=db.backref('states', lazy='dynamic'))
    last_updated = db.Column('last_updated', db.DateTime, default=datetime.now, onupdate=datetime.now)
    rferror = db.Column(db.Boolean, nullable=True)
    signal_strength = db.Column(db.Integer, nullable=True)
    desired_temperature = db.Column(db.Float, nullable=True)
    is_locked = db.Column(db.Boolean, nullable=True)
    valve_position = db.Column(db.Integer, nullable=True)
    lan_gateway = db.Column(db.Boolean, nullable=True)
    dstsetting = db.Column(db.Boolean, nullable=True)
    mode = db.Column(db.Integer, nullable=True)
    measured_temperature = db.Column(db.Float, nullable=True)
    battery_low = db.Column(db.Boolean, nullable=True)


#
# Signal responders
#
@device_pair_request.connect
def create_new_device(sender, **kw):
    msg = kw['msg']
    entry = Devices.query.filter_by(sender_id=msg.sender_id).first()
    if entry is None:
        entry = Devices(msg.sender_id, msg.decoded_payload['device_serial'], msg.decoded_payload['device_type'])
        entry.firmware_version = msg.decoded_payload['firmware_version']
        db.session.add(entry)
        db.session.commit()

@device_pair_accepted.connect
def activate_device(sender, **kw):
    msg = kw['resp_msg']
    entry = Devices.query.filter_by(sender_id=msg.receiver_id).first()
    if entry is None:
        entry = Devices(msg.receiver_id, "Unknown")
    entry.paired = True
    db.session.add(entry)
    db.session.commit()

@thermostatstate_received.connect
def store_thermostatstate(sender, **kw):
    msg = kw['msg']
    thermostat = Devices.query.filter_by(sender_id=msg.sender_id, device_type="HeatingThermostat").first()
    if thermostat is None:
        return
    thermostat_state = ThermostatState()
    thermostat_state.thermostat = thermostat
    decoded_payload = msg.decoded_payload
    for parameter in ["last_updated", "rferror", "signal_strength", "desired_temperature",
                      "is_locked", "valve_position", "lan_gateway", "dstsetting", "mode",
                      "measured_temperature", "battery_low",]:
        if parameter in decoded_payload:
            setattr(thermostat_state, parameter, decoded_payload[parameter])
    db.session.add(thermostat_state)
    db.session.commit()

#
# Views
#
@app.route("/")
def index():
    return "<a href='" + url_for("get_devices") + "'>Tracked devices</a><br>" + \
           "<a href='" + url_for("current_thermostat_states") + "'>Current thermostat states</a><br>" + \
           "<a href='" + url_for("current_shuttercontact_states") + "'>Current shuttercontact states</a><br>" + \
           "<a href='" + url_for("current_wallthermostat_states") + "'>Current wallthermostat states</a><br>" + \
           "<a href='" + url_for("set_temp") + "'>Set one temp</a><br>" + \
           "<a href='" + url_for("set_time") + "'>Set time</a><br>" + \
           "<a href='" + url_for("set_boost_config") + "'>Set boost</a><br>" + \
           "<a href='" + url_for("set_groupId") + "'>Set group id</a><br>" + \
           "<a href='" + url_for("set_assoc") + "'>Set assoc</a><br>" + \
           "<a href='" + url_for("set_config_temperature") + "'>Set config temperature</a><br>" + \
           "<a href='" + url_for("set_temp_all") + "'>Set temp on all sensors</a>"

@app.route("/current_thermostat_states")
def current_thermostat_states():
    with message_thread.thermostat_states_lock:
        return json.dumps(message_thread.thermostat_states, indent=4, sort_keys=True, cls=JSONWithDateEncoder)

@app.route("/current_shuttercontact_states")
def current_shuttercontact_states():
    with message_thread.shuttercontact_states_lock:
        return json.dumps(message_thread.shuttercontact_states, indent=4, sort_keys=True, cls=JSONWithDateEncoder)

@app.route("/current_wallthermostat_states")
def current_wallthermostat_states():
    with message_thread.wallthermostat_states_lock:
        return json.dumps(message_thread.wallthermostat_states, indent=4, sort_keys=True, cls=JSONWithDateEncoder)


@app.route("/get_devices")
def get_devices():
    devices = []
    for device in Devices.query.all():
        devices.append({
            'sender_id': device.sender_id,
            'serial': device.serial,
            'firmware_version': device.firmware_version,
            'name': device.name,
            'paired': device.paired,
            'device_type': device.device_type,
        })
    return json.dumps(devices)

@app.route("/set_temp", methods=["GET", "POST"])
def set_temp():
    if not request.form:
        content = """<html><form action="" method="POST"><select name="thermostat">"""
        for thermostat in Devices.query.filter_by(paired=True):
            content += """<option value="%s">%s %s</option>""" % (thermostat.sender_id, thermostat.name, thermostat.device_type)
        content += """</select><select name="mode"><option>auto</option><option selected>manual</option><option>boost</option></select>"""
        content += """<input type=text name=temperature><input type=submit value="set"></form></html>"""
        return content
    msg = SetTemperatureMessage()
    msg.counter = 0xB9
    msg.sender_id = CUBE_ID
    msg.receiver_id = int(request.form['thermostat'])
    msg.group_id = 0
    payload = {
        'desired_temperature': float(request.form["temperature"]),
        'mode': request.form["mode"],
    }
    command_queue.put((msg, payload))
    return """<html>Done. <a href="/">back</a>"""

@app.route("/set_time", methods=["GET", "POST"])
def set_time():
    if not request.form:
        content = """<html><form action="" method="POST"><select name="device">"""
        for device in Devices.query.filter_by(paired=True):
            content += """<option value="%s">%s</option>""" % (device.sender_id, device.name)
        content += """<input type=submit value="set"></form></html>"""
        return content
    msg = TimeInformationMessage()
    msg.counter = 2
    msg.sender_id = CUBE_ID
    msg.receiver_id = int(request.form['device'])
    msg.group_id = 0
    payload = datetime.now()
    command_queue.put((msg, payload))
    return """<html>Done. <a href="/">back</a>"""

@app.route("/set_boost_config", methods=["GET", "POST"])
def set_boost_config():
    if not request.form:
        content = """<html><form action="" method="POST"><select name="thermostat">"""
        for thermostat in Devices.query.filter_by(paired=True, device_type="HeatingThermostat"):
            content += """<option value="%s">%s</option>""" % (thermostat.sender_id, thermostat.name)
        content += """</select><select name="mode"><option>auto</option><option selected>manual</option><option>boost</option></select>"""
        content += """<input type=text name=temperature><input type=submit value="set"></form></html>"""
        return content
    msg = ConfigValveMessage()
    msg.counter = 0xB9
    msg.sender_id = CUBE_ID
    msg.receiver_id = int(request.form['thermostat'])
    msg.group_id = 0
    payload = {
        'boost_duration': 5,
        'boost_valve_position': 100,
        'boost': '54',
        'decalc_day': "Sat",
        'decalc_hour': 12,
        'decalc': '8c',
        'max_valve_position': 100,
        'valve_offset': 0
    }
    command_queue.put((msg, payload))
    return """<html>Done. <a href="/">back</a>"""

@app.route("/set_config_temperature", methods=["GET", "POST"])
def set_config_temperature():
    if not request.form:
        content = """<html><form action="" method="POST"><select name="thermostat">"""
        for thermostat in Devices.query.filter_by(paired=True, device_type="HeatingThermostat"):
            content += """<option value="%s">%s</option>""" % (thermostat.sender_id, thermostat.name)
        content += """<input type=text name=temperature><input type=submit value="set"></form></html>"""
        return content
    msg = ConfigTemperaturesMessage()
    msg.counter = 0xB9
    msg.sender_id = CUBE_ID
    msg.receiver_id = int(request.form['thermostat'])
    msg.group_id = 0
    payload = {
        'comfort_Temperature': 20,
        'eco_Temperature': 16,
        'max_Temperature': 22,
        'min_Temperature': 10,
        'measurement_Offset': 0,
        'window_Open_Temperatur': 12,
        'window_Open_Duration': 15,
    }
    command_queue.put((msg, payload))
    return """<html>Done. <a href="/">back</a>"""


@app.route("/set_groupId", methods=["GET", "POST"])
def set_groupId():
    if not request.form:
        content = """<html><form action="" method="POST"><select name="device">"""
        for device in Devices.query.filter_by(paired=True):
            content += """<option value="%s">%s</option>""" % (device.sender_id, device.name)
        content += """<input type=text name=groupId><input type=submit value="set"></form></html>"""
        return content
    msg = SetGroupIdMessage()
    msg.counter = 0xB9
    msg.sender_id = CUBE_ID
    msg.receiver_id = int(request.form['device'])
    msg.group_id = 0
    payload = {
        'group_id':  int(request.form["groupId"])
    }
    command_queue.put((msg, payload))
    return """<html>Done. <a href="/">back</a>"""

@app.route("/set_assoc", methods=["GET", "POST"])
def set_assoc():
    devices = Devices.query.filter_by(paired=True)
    if not request.form:
        content = """<html><form action="" method="POST"><select name="device">"""
        for device in devices:
            content += """<option value="%s">%s %s</option>""" % (device.sender_id, device.name, device.device_type)

        content += """</select><select name="assocDevice">"""

        for device in devices:
            content += """<option value="%s">%s %s</option>""" % (device.sender_id, device.name, device.device_type)
        content += """<input type=submit value="set"></form></html>"""
        return content
    msg = AddLinkPartnerMessage()
    msg.counter = 0xB9
    msg.sender_id = CUBE_ID
    msg.receiver_id = int(request.form['device'])
    msg.group_id = 0
    payload = {
        'assocDevice':  request.form["assocDevice"],
        'assocDeviceType': devices.filter_by(sender_id=request.form["assocDevice"]).one().device_type
    }
    command_queue.put((msg, payload))
    return """<html>Done. <a href="/">back</a>"""



@app.route("/set_temp_all", methods=["GET", "POST"])
def set_temp_all():
    if not request.form:
        content = """<html><form action="" method="POST"><select name="mode"><option>auto</option><option selected>manual</option><option>boost</option></select>"""
        content += """<input type=text name=temperature><input type=submit value="set"></form></html>"""
        return content
    for thermostat in Devices.query.filter_by(paired=True, device_type="HeatingThermostat"):
        msg = SetTemperatureMessage()
        msg.counter = 0xB9
        msg.sender_id = CUBE_ID
        msg.receiver_id = thermostat.sender_id
        msg.group_id = 0
        payload = {
            'desired_temperature': float(request.form["temperature"]),
            'mode': request.form["mode"],
        }
        command_queue.put((msg, payload))
    return """<html>Done. <a href="/">back</a>"""

#
# Execution
#
def main(args):
    global message_thread
    message_thread = CULMessageThread(command_queue, args.cul_path, args.cul_baud)
    message_thread.start()

    if args.flask_debug:
        app.run(host="0.0.0.0", port=12345, debug=True, use_reloader=False)
    else:
        app.run(host="0.0.0.0", port=12345)

    message_thread.join()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--flask-debug", action="store_true", help="Enables Flask debug and reload. May cause weird behaviour.")
    parser.add_argument("--detach", action="store_true", help="Detach from terminal")
    parser.add_argument("--cul-path", default="/dev/ttyACM0", help="Path to usbmodem path of CUL, defaults to /dev/ttyACM0")
    parser.add_argument("--cul-baud", default="38400", help="Baudrate of the cul serial connection.")
    args = parser.parse_args()

    db.create_all()

    if args.detach:

        # init logger
        from logbook import FileHandler
        log_handler = FileHandler('server.log')
        log_handler.push_application()

        import detach
        with detach.Detach(daemonize=True) as d:
            if d.pid:
                print("started process {} in background with log to server.log".format(d.pid))
            else:
                main(args)
    else:
        # init logger
        from logbook.more import ColorizedStderrHandler
        log_handler = ColorizedStderrHandler()
        log_handler.push_application()

        main(args)
