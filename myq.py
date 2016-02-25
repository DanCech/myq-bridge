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

        raise MyQException('Door {} not found'.format(name), 3)

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

                name = None
                state = None
                changed = None

                for attr in device['Attributes']:
                    if attr['Name'] == 'desc':
                        name = attr['Value']
                    elif attr['Name'] == 'doorstate':
                        changed = time.localtime(
                            float(attr['UpdatedTime']) / 1000.0)

                        state = Door.STATES[int(attr['Value'])]

                if id in self.doors:
                    doors[id] = self.doors[id]
                    doors[id].update_name(name)
                    doors[id].update_state(state, changed)
                else:
                    doors[id] = Door(self, id, name, state, changed)

        self.doors = doors

        return self.doors

    def put(self, url, payload):
        put_url = self.SERVICE + url

        payload['ApplicationId'] = self.APPID
        payload['SecurityToken'] = self.get_token()

        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug('PUT ' + url + ' Request: ' + self.logdata(payload))

        try:
            r = requests.put(put_url, data=payload)
        except requests.exceptions.RequestException as err:
            raise MyQException('Caught Exception: ' + err, 2)

        data = r.json()

        LOGGER.debug('PUT ' + url + ' Response: ' + self.logdata(data))

        if data['ReturnCode'] != '0':
            raise MyQException(data['ErrorMessage'], 1)

        return data

    def get(self, url, params={}, token=None):
        if token is None:
            token = self.get_token()

        get_url = self.SERVICE + url

        params['appId'] = self.APPID
        params['securityToken'] = token

        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug('GET ' + url + ' Request: ' + self.logdata(params))

        try:
            r = requests.get(get_url, params=params)
        except requests.exceptions.RequestException as err:
            raise MyQException('Caught Exception: ' + err, 2)

        data = r.json()

        LOGGER.debug('GET ' + url + ' Response: ' + self.logdata(data))

        if data['ReturnCode'] != '0':
            raise MyQException(data['ErrorMessage'], 1)

        return data

    def logdata(self, params):
        protect = ['password', 'securityToken', 'SecurityToken']
        return json.dumps({
            x: (y if x not in protect else '***')
            for x, y in params.items()
        }, sort_keys=True, indent=2)


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

        self.update_name(name)
        self.update_state(state, changed)

    def update_name(self, name=None):
        if name is None:
            data = self.myq.get(
                '/Device/getDeviceAttribute',
                {
                    'devId': self.id,
                    'name': 'desc',
                })

            name = data['AttributeValue']

        self.name = name

    def update_state(self, state=None, changed=None):
        if state is None or changed is None:
            data = self.myq.get(
                '/Device/getDeviceAttribute',
                {
                    'devId': self.id,
                    'name': 'doorstate',
                })

            state = self.STATES[int(data['AttributeValue'])]
            changed = time.localtime(float(data['UpdatedTime']) / 1000.0)

        self.state = state
        self.changed = changed
        self.updated = time.localtime()

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
            if self.state in ['Closed', 'Closing']:
                raise MyQException(
                    '{} already {}.'.format(self.name, self.state), 6)

            desired_state = 0
        elif desired_state.lower() == 'open':
            if self.state in ['Open', 'Opening']:
                raise MyQException(
                    '{} already {}.'.format(self.name, self.state), 6)

            desired_state = 1
        else:
            raise MyQException('Invalid state specified', 7)

        self.myq.put(
            '/api/deviceattribute/putdeviceattribute',
            {
                'AttributeName': 'desireddoorstate',
                'DeviceId': self.id,
                'AttributeValue': desired_state,
            })

        self.update_state()

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

        self.var_ids = {}

    def update_door(self, door):
        if not self.enabled:
            return

        id, varname = self.get_var_id(door.name)
        if door.state == "Open":
            value = 1
        else:
            value = 0
        self.set_var_state(id, varname, value)

    def set_var_state(self, id, varname, value):
        init, val = self.get_var_state(id)
        if value == int(val):
            LOGGER.debug('%s is already set to %s', varname, val)
            return True

        r = self.call('/rest/vars/set/2/' + id + '/' + str(value))

        if int(r.status_code) == 404:
            LOGGER.error('%s not found on ISY. Response was 404', id)
            return False

        if int(r.status_code) != 200:
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

        if varname in self.var_ids:
            return self.var_ids[varname], varname

        LOGGER.info('Searching ISY Definitions for %s', varname)

        r = self.call('/rest/vars/definitions/2')
        tree = ElementTree.fromstring(r.text)

        var_ids = {}
        for e in tree.findall('e'):
            var_ids[e.get('name')] = e.get('id')

        self.var_ids = var_ids

        if varname in self.var_ids:
            LOGGER.info('State variable: %s found with ID: %s', varname, id)
            return self.var_ids[varname], varname

        raise Exception(
            "State variable: {} not found in ISY variable list".format(
                varname))

    def call(self, url):
        try:
            r = requests.get(
                'http://' + self.host + ':' + self.port + url,
                auth=HTTPBasicAuth(self.username, self.password))
        except requests.exceptions.RequestException as err:
            raise Exception('Error calling ISY {}: {}'.format(url, err))

        return r


def main():
    LOGGER.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    LOGGER.addHandler(handler)

    LOGGER.info('Starting')

    try:
        config = RawConfigParser()
        config.read('myq.cfg')

        if (config.has_option('MyQ', 'debug')
                and config.getboolean('MyQ', 'debug')):
            LOGGER.setLevel(logging.DEBUG)

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

    @app.route('/doors/<doorname>')
    def door_status(doorname):
        try:
            door = myq.get_door(doorname.replace('+', ' '))
            door.update_state()

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

    @app.route('/doors/<doorname>/<state>')
    def door_handler(doorname, state):
        try:
            door = myq.get_door(doorname.replace('+', ' '))

            door.update_state()
            isy.update_door(door)

            LOGGER.info(
                '%s is %s. Last changed at %s',
                door.name, door.state, door.format_changed)

            if state == 'status':
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
