This is a simple Flask server that provides a straightforward HTTP interface to control MyQ garage door openers.

Based on https://github.com/Einstein42/myq-garage/blob/master/myq-garage.py

To configure, copy `myq.default.cfg` to `myq.cfg` and enter your MyQ username and password.

To enable the ISY integration, configure the details of your ISY and set the `enabled` item to `true`.

By default the bridge listens for http requests on localhost port 5000, to listen on a different port update the `Flask` `host` and `port` in `myq.cfg`.

To get a list of doors: http://localhost:5000/doors/

To get details of a door: http://localhost:5000/doors/Main+Door

To get status of a door: http://localhost:5000/doors/Main+Door/status

To open a door: http://localhost:5000/doors/Main+Door/open

To close a door: http://localhost:5000/doors/Main+Door/close