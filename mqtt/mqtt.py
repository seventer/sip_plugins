# !/usr/bin/env python
from __future__ import print_function
""" SIP plugin adds an MQTT client to SIP for other plugins to broadcast and receive via MQTT
The intent is to facilitate joining SIP to larger automation systems
"""
__author__ = "Daniel Casner <daniel@danielcasner.org> Modifications by Gerard (seventer@live.nl)"

import web  # web.py framework
import gv  # Get access to SIP's settings
from urls import urls  # Get access to SIP's URLs
from sip import template_render  #  Needed for working with web.py templates
from webpages import ProtectedPage  # Needed for security
import json  # for working with data file
import atexit # For publishing down message
from blinker import signal # receive heartbeat notifications

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: MQTT Plugin requires paho mqtt.")
    print("\ttry: pip install paho-mqtt")
    mqtt = None

DATA_FILE = "./data/mqtt.json"

_client = None
_client_connected = False

_settings = {
    'broker_host': 'localhost',
    'broker_port': 1883,
    'broker_alive': 60,
    'publish_up_down': ''
}
_subscriptions = {}
#tmp_subscriptions = {}


# Add new URLs to access classes in this plugin.
urls.extend([
    '/mqtt-sp', 'plugins.mqtt.settings',
    '/mqtt-save', 'plugins.mqtt.save_settings'
    ])
gv.plugin_menu.append(['MQTT', '/mqtt-sp'])

NO_MQTT_ERROR = "MQTT plugin requires paho mqtt python library. On the command line run `pip install paho-mqtt` and restart SIP to get it."

class settings(ProtectedPage):
    """Load an html page for entering plugin settings.
    """
    def GET(self):
        settings = get_settings()
        return template_render.mqtt(settings, gv.sd[u'name'], NO_MQTT_ERROR if mqtt is None else "")  # open settings page

class save_settings(ProtectedPage):
    """Save user input to json file.
    Will create or update file when SUBMIT button is clicked
    CheckBoxes only appear in qdict if they are checked.
    """

    def GET(self):
        qdict = web.input()  # Dictionary of values returned as query string from settings page.
        with open(DATA_FILE, 'w') as f:
            try:
                port = int(qdict['broker_port'])
                alive = int(qdict['broker_alive'])
                assert port > 80 and port < 65535
                assert alive > 1 and alive < 2400
                _settings['broker_port'] = port
                _settings['broker_alive'] = alive
                _settings['broker_host'] = qdict['broker_host']
                _settings['publish_up_down'] = qdict['publish_up_down']
            except:
                return template_render.proto(qdict, gv.sd[u'name'], "Broker port and keepalive must be a valid integer port number")
            else:
                json.dump(_settings, f) # save to file
                publish_status()
        raise web.seeother('/')  # Return user to home page.

def get_settings():
    global _settings
    try:
        fh = open(DATA_FILE, 'r')
        try:
            _settings = json.load(fh)
        except ValueError as e:
            print("MQTT pluging couldn't parse data file:", e)
        finally:
            fh.close()
    except IOError as e:
        print("MQTT Plugin couldn't open data file:", e)
    return _settings

def on_message(client, userdata, msg):
    "Callback for MQTT data recieved"
    #global _subscriptions
    if not msg.topic in _subscriptions:
        print("MQTT plugin got unexpected message on topic:", msg.topic)
    else:
        for cb in _subscriptions[msg.topic]:
            cb(client, msg)

def setup_client():
    global _client
    
    if _client is None and mqtt is not None:
        try:
            if (_settings['broker_alive'] < 1 or _settings['broker_alive'] > 2400 ):
                _settings['broker_alive'] = 60
            _client = mqtt.Client(gv.sd[u'name']) # Use system name as client ID
            _client.on_message = on_message
            _client.on_log=on_log
            _client.on_connect = on_connect
            _client.on_disconnect = on_disconnect
        except Exception as e:
            print("MQTT plugin couldn't setup client:", e)
            _client = None
    else:
        print("MQTT client already setup. Nothing to do.")
    return _client

def start_client():
    global _client
    global _client_connected
    
    if _client is None:
        setup_client()
    
    if _client and _client_connected==False:
        try:
            _client.connect(_settings['broker_host'], _settings['broker_port'], _settings['broker_alive'])
            if _settings['publish_up_down']:
                _client.will_set(_settings['publish_up_down'], json.dumps("DIED"), qos=1, retain=True)
            _client.loop_start()
        except Exception as e:
            print("MQTT plugin couldn't start client:", e)
    else:
        print("MQTT client not initialised")
    return _client

# is this still usefull? Yes for now, it's used by other plugins
def get_client():
    global _client
    return _client


def publish_status(status="UP"):
    global _settings
    if _settings['publish_up_down']:
        print("MQTT publish", status)
        client = get_client()
        if client:
            client.publish(_settings['publish_up_down'], json.dumps(status), qos=1, retain=True)


def subscribe(topic, callback, qos=0):
    "Subscribes to a topic with the given callback"
    global _subscriptions
    ok=False
    client = get_client()
    if client:
        if topic not in _subscriptions:
            t = client.subscribe(topic, qos)
            print('MQTT subscribe resonse: ', t)
            if t[0]==0:
                _subscriptions[topic] = [callback]
                ok=True
        else:
            _subscriptions[topic].append(callback)
    else:
        print("MQTT Subscribe: client not initialised yet")
    return ok


def on_restart():
    global _client
    global _client_connected
    if _client is not None and _client_connected:
        publish_status("DOWN")
        _client.disconnect()
        _client.loop_stop()
        _client_connected=False
        _client = None


def on_log(client, userdata, level, buf):
    print("MQTT on_log:" + buf)

def on_disconnect(client, userdata, rc):
    global _client
    global _client_connected
    global _subscriptions
    if rc != 0:
        print("MQTT Unexpected disconnection. rc=",rc)
        _client.loop_stop()
        _subscriptions = {}
        _client_connected=False
        _client = None


def on_connect(client, userdata, flags, rc):
    global _client_connected
    #print("MQTT Connection returned result: "+ str(rc))
    if rc==0:
        print("MQTT connected OK Returned code=",rc)
        _client_connected=True
        publish_status()
    else:
        print("MQTT failed to connect. rc=",rc)
    
def notify_heartbeat(name, **kw):
    #global _client_connected
    print("MQTT received hearbeat signal")
    if _client_connected==False:
        print("MQTT not connected, attempting to....")
        get_settings()
        if not _client_connected:
            start_client()

def is_connected():
    return _client_connected 
    
beat = signal('sip_heartbeat')
beat.connect(notify_heartbeat)

atexit.register(on_restart)
start_client()
