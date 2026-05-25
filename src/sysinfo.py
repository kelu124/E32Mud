"""
System information for E32Mud.
Imported lazily (only when admin runs the `sysinfo` command) to save RAM.

Every probe is wrapped in try/except so it degrades gracefully on firmware
builds that lack a given API.
"""
import sys
import gc
import os


def get_sysinfo():
    """Return a multi-line string with all available system diagnostics."""
    lines = []
    on_esp = 'esp' in sys.platform

    # ---- Platform / firmware ----
    lines.append("--- Platform ---")
    lines.append("sys.platform:  " + sys.platform)
    lines.append("sys.version:   " + sys.version)
    try:
        impl = sys.implementation
        ver = ".".join(str(x) for x in impl.version)
        lines.append("Implementation: " + impl.name + " " + ver)
    except Exception:
        pass
    try:
        u = os.uname()
        lines.append("Machine:  " + u.machine)
        lines.append("Release:  " + u.release)
        lines.append("Sysname:  " + u.sysname)
    except Exception:
        pass

    # ---- CPU ----
    if on_esp:
        lines.append("")
        lines.append("--- CPU ---")
        try:
            import machine
            freq = machine.freq()
            lines.append("CPU freq: " + str(freq // 1_000_000) + " MHz")
        except Exception:
            pass
        try:
            import machine
            uid = machine.unique_id()
            lines.append("Chip ID:  " + uid.hex())
        except Exception:
            pass

    # ---- RAM ----
    lines.append("")
    lines.append("--- RAM ---")
    gc.collect()
    try:
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        total = free + alloc
        pct = alloc * 100 // total if total else 0
        lines.append("Used:  " + str(alloc) + " / " + str(total) + " bytes (" + str(pct) + "%)")
        lines.append("Free:  " + str(free) + " bytes")
    except Exception:
        lines.append("(gc.mem_free / gc.mem_alloc not available)")

    # ---- Storage ----
    lines.append("")
    lines.append("--- Storage ---")
    try:
        s = os.statvfs('/')
        block_size   = s[0]
        total_blocks = s[2]
        free_blocks  = s[3]
        total = block_size * total_blocks
        free  = block_size * free_blocks
        used  = total - free
        pct   = used * 100 // total if total else 0
        lines.append("Used:  " + str(used) + " / " + str(total) + " bytes (" + str(pct) + "%)")
        lines.append("Free:  " + str(free) + " bytes")
    except Exception:
        lines.append("(os.statvfs not available)")

    if on_esp:
        try:
            import esp
            lines.append("Flash chip: " + str(esp.flash_size()) + " bytes")
        except Exception:
            pass

    # ---- Temperature (ESP32 only) ----
    if on_esp:
        try:
            import esp32
            try:
                t = esp32.mcu_temperature()
                lines.append("")
                lines.append("--- Temperature ---")
                lines.append("MCU temp: " + str(t) + " C")
            except Exception:
                t_f = esp32.raw_temperature()
                t_c = (t_f - 32) * 5 / 9
                lines.append("")
                lines.append("--- Temperature ---")
                lines.append("MCU temp: " + str(int(t_c)) + " C (raw " + str(t_f) + " F)")
        except Exception:
            pass

    # ---- WiFi (ESP32 AP mode) ----
    if on_esp:
        try:
            import network
            ap = network.WLAN(network.AP_IF)
            if ap.active():
                lines.append("")
                lines.append("--- WiFi AP ---")
                cfg = ap.ifconfig()
                lines.append("IP:     " + cfg[0])
                try:
                    lines.append("SSID:   " + ap.config('essid'))
                except Exception:
                    pass
                try:
                    stations = ap.status('stations')
                    lines.append("Clients: " + str(len(stations)))
                except Exception:
                    pass
        except Exception:
            pass

    # ---- Uptime ----
    try:
        import time
        ms = time.ticks_ms()
        secs = ms // 1000
        mins, secs = divmod(secs, 60)
        hrs, mins = divmod(mins, 60)
        days, hrs = divmod(hrs, 24)
        lines.append("")
        lines.append("--- Uptime ---")
        lines.append(str(days) + "d " + str(hrs) + "h " + str(mins) + "m " + str(secs) + "s")
    except Exception:
        pass

    return "\n".join(lines)
