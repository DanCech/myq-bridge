#!/usr/bin/env python2.7

# Python to interface with MyQ garage doors.

"""
The MIT License (MIT)

Copyright (c) 2015

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import flask
import requests
from requests.auth import HTTPBasicAuth
# from requests.utils import quote
import sys
import time
import json
import logging
# Try to use the C implementation first, falling back to python.
try:
    from xml.etree import cElementTree as ElementTree
except ImportError:
    from xml.etree import ElementTree
# compatibility with python 3
try:
    from ConfigParser import RawConfigParser
except ImportError:
    from configparser import RawConfigParser

requests.packages.urllib3.disable_warnings()

LOGGER = logging.getLogger(__name__)


class MyQ(object):
    # Do not change this is the URL for the MyQ API
    SERVICE = 'https://myqexternal.myqdevice.com'

    # Do not change the APPID or CULTURE this is global for the MyQ API
    APPID = \
        'Vj8pQggXLhLy0WHahglCD4N1nAkkXQtGYpq2HrHD7H1nvmbT55KqtN6RSF4ILB%2fi'
    CULTURE = 'en'

    def __init__(self, username, password):
        self.doors = {}

        self.token = None
        self.token_expiry = None

        self.username = username
        self.password = password

    def get_door(self, name):
        for id, door in self.get_doors().items():
            if door.name == name or door.id == name:
                return door

        raise MyQException('Door not found', 3)

    def get_token(self):
        if self.token_expiry > time.time():
            return self.token

        data = self.get(
            '/Membership/ValidateUserWithCulture',
            {
                'username': self.username,
                'password': self.password,
                'culture': self.CULTURE,
            },
            token='null')

        self.token = data['SecurityToken']
        self.token_expiry = time.time() + 1800

        return self.token

    def get_doors(self, refresh=False):
        if self.doors and not refresh:
            return self.doors

        doors = {}

        data = self.get('/api/UserDeviceDetails')

        for device in data['Devices']:
            # Doors == 2, Gateway == 1, Structure == 10, Thermostat == 11
            if device['MyQDeviceTypeId'] == 2:
                id = device['DeviceId']
                if id in self.doors:
                    doors[id] = self.doors[id]
                    doors[id].get_state()
                else:
                    doors[id] = Door(self, id)

        self.doors = doors

        return self.doors

    def put(self, url, payload):
        put_url = self.SERVICE + url

        payload['ApplicationId'] = self.APPID
        payload['SecurityToken'] = self.get_token()

        try:
            r = requests.put(put_url, data=payload)
        except requests.exceptions.RequestException as err:
            raise MyQException('Caught Exception: ' + err, 2)

        data = r.json()
        if data['ReturnCode'] != '0':
            raise MyQException(data['ErrorMessage'], 1)

        return data

    def get(self, url, params={}, token=None):
        if token is None:
            token = self.get_token()

        get_url = self.SERVICE + url

        params['appId'] = self.APPID
        params['securityToken'] = token

        try:
            r = requests.get(get_url, params=params)
        except requests.exceptions.RequestException as err:
            raise MyQException('Caught Exception: ' + err, 2)

        data = r.json()
        if data['ReturnCode'] != '0':
            raise MyQException(data['ErrorMessage'], 1)

        return data


class Door(object):
    # State value from API returns an integer, the index corresponds to the
    # below list. Zero is not used.
    STATES = [
        '',
        'Open',
        'Closed',
        'Stopped',
        'Opening',
        'Closing',
    ]

    def __init__(self, myq, id, name=None, state=None, changed=None):
        self.myq = myq
        self.id = id

        if name is None:
            self.get_name()
        else:
            self.name = name

        if state is None or changed is None:
            self.get_state()
        else:
            self.state = state
            self.changed = changed
            self.updated = time.localtime()

    def get_id(self):
        return self.id

    def get_name(self):
        data = self.myq.get(
            '/Device/getDeviceAttribute',
            {
                'devId': self.id,
                'name': 'desc',
            })

        self.name = data['AttributeValue']

        return self.name

    def get_state(self):
        data = self.myq.get(
            '/Device/getDeviceAttribute',
            {
                'devId': self.id,
                'name': 'doorstate',
            })

        timestamp = float(data['UpdatedTime'])
        timestamp = time.localtime(timestamp / 1000.0)

        self.state = self.STATES[int(data['AttributeValue'])]
        self.changed = timestamp
        self.updated = time.localtime()

        return self.state, self.changed

    @property
    def format_changed(self):
        return time.strftime(
            "%a %d %b %Y %H:%M:%S", self.changed)

    @property
    def format_updated(self):
        return time.strftime(
            "%a %d %b %Y %H:%M:%S", self.updated)

    def set_state(self, desired_state):
        if desired_state.lower() == 'close':
            desired_state = 0
        elif desired_state.lower() == 'open':
            desired_state = 1
        else:
            raise MyQException('Invalid state specified', 7)

        if self.state == 'Open' and desired_state == 1:
            raise MyQException(self.name + ' already open.', 5)

        if self.state == 'Closed' and desired_state == 0:
            raise MyQException(self.name + ' already closed.', 6)

        self.myq.put(
            '/api/deviceattribute/putdeviceattribute',
            {
                'AttributeName': 'desireddoorstate',
                'DeviceId': self.id,
                'AttributeValue': desired_state,
            })

        return True


class MyQException(Exception):
    def __init__(self, msg, code=1):
        LOGGER.error(msg)
        self.code = code
        super(MyQException, self).__init__(msg)


class ISY(object):
    def __init__(self, host, port, username, password, var_prefix,
                 enabled=True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.var_prefix = var_prefix
        self.enabled = enabled

    def update_door(self, door):
        if not self.enabled:
            return

        id, varname, init, value = self.get_var_id(door.name)
        if door.state == "Open":
            value = 1
        else:
            value = 0
        self.set_var_state(id, door.name, varname, value)

    def set_var_state(self, id, name, varname, value):
        init, val = self.get_var_state(id)
        if value == int(val):
            LOGGER.debug('%s is already set to %s', varname, val)
            return True

        r = self.call('/rest/vars/set/2/' + id + '/' + str(value))

        if int(r.status_code) != 200:
            if int(r.status_code) == 404:
                LOGGER.error('%s not found on ISY. Response was 404', id)
            else:
                LOGGER.error(
                    'Status change failed, response from ISY: %s - %s',
                    r.status_code, r.text)
            return False

        LOGGER.info('%s changed successfully to %s', varname, value)
        return True

    def get_var_state(self, id):
        r = self.call('/rest/vars/get/2/' + id)
        tree = ElementTree.fromstring(r.text)

        init = tree.find('init').text
        value = tree.find('val').text

        LOGGER.info('Get_Var_State: init: %s - val: %s', init, value)
        return init, value

    def get_var_id(self, name):
        varname = str(self.var_prefix + name.replace(" ", "_"))

        r = self.call('/rest/vars/definitions/2')
        tree = ElementTree.fromstring(r.text)

        LOGGER.info('Searching ISY Definitions for %s', varname)
        valid = False
        for e in tree.findall('e'):
            if e.get('name') != varname:
                continue

            valid = True
            id = e.get('id')
            name = e.get('name')
            break

        if not valid:
            raise Exception(
                "State variable: {} not found in ISY variable list".format(
                    varname))

        # id, name = child.get('id'), child.get('name')
        LOGGER.info('State variable: %s found with ID: %s', name, id)

        init, value = self.get_var_state(id)
        LOGGER.info(
            'ISY Get Var ID Return id=%s varname=%s init=%s value=%s',
            id, varname, init, value)
        return id, varname, init, value

    def call(self, url):
        try:
            r = requests.get(
                'http://' + self.host + ':' + self.port + url,
                auth=HTTPBasicAuth(self.username, self.password))
        except requests.exceptions.RequestException as err:
            LOGGER.error('Error getting {}: {}'.format(url, err))
            return

        return ElementTree.fromstring(r.text)


def main():
    LOGGER.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    LOGGER.addHandler(handler)

    LOGGER.info('Starting')

    try:
        config = RawConfigParser()
        config.read('myq.cfg')

        myq = MyQ(
            config.get('MyQ', 'username'),
            config.get('MyQ', 'password'),
        )

        isy = ISY(
            config.get('ISY', 'host'),
            config.get('ISY', 'port'),
            config.get('ISY', 'username'),
            config.get('ISY', 'password'),
            config.get('ISY', 'var_prefix'),
            config.getboolean('ISY', 'enabled'),
        )
    except Exception as e:
        LOGGER.error(e)
        return 1

    app = flask.Flask(__name__)

    def make_response(ret, http_status=200):
        response = flask.make_response(json.dumps(ret), http_status)
        response.mimetype = 'application/json'
        return response

    def make_error(e):
        return make_response(
            {'error': str(e), 'code': getattr(e, 'code', None)}, 500)

    @app.route('/doors/')
    def doors_status():
        try:
            ret = []
            for id, door in myq.get_doors(True).items():
                LOGGER.info(
                    '%s is %s. Last changed at %s',
                    door.name, door.state, door.format_changed)

                isy.update_door(door)

                ret.append({
                    'id': door.id,
                    'name': door.name,
                    'state': door.state,
                    'changed': door.format_changed,
                    'updated': door.format_updated,
                })

            return make_response(ret)
        except Exception as e:
            return make_error(e)

    @app.route('/doors/<string:doorname>')
    def door_status(doorname):
        try:
            door = myq.get_door(doorname)
            door.get_state()

            LOGGER.info(
                '%s is %s. Last changed at %s',
                door.name, door.state, door.format_changed)

            isy.update_door(door)

            ret = {
                'id': door.id,
                'name': door.name,
                'state': door.state,
                'changed': door.format_changed,
                'updated': door.format_updated,
            }

            return make_response(ret)
        except Exception as e:
            return make_error(e)

    @app.route('/doors/<string:doorname>/<string:state>')
    def door_handler(doorname, state):
        try:
            door = myq.get_door(doorname)
            if state == 'status':
                door.get_state()
                isy.update_door(door)
                ret = door.state
            else:
                door.set_state(state)
                ret = 'OK'

            response = flask.make_response(ret)
            response.mimetype = 'text/plain'
            return response
        except Exception as e:
            return make_error(e)

    LOGGER.info('Getting Doors')
    try:
        myq.get_doors()
    except MyQException as e:
        LOGGER.error(e)
        return 1

    app.run(
        host=config.get('Flask', 'host'),
        port=config.getint('Flask', 'port'),
        debug=config.getboolean('Flask', 'debug'),
    )
    return 0

if __name__ == '__main__':
    sys.exit(main())
