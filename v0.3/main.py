import network

if 1:

    wlan = network.WLAN(network.AP_IF)
    wlan.active(True)
    wlan.config(essid='OpenMUD_4000')
                 
from captive import start_dns_server

import _thread
_thread.start_new_thread(start_dns_server, ())


import mud