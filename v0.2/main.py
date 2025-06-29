import network

if 1:

    wlan = network.WLAN(network.AP_IF)
    wlan.active(True)
    wlan.config(essid='OpenMUD_4000')
                 

import mud