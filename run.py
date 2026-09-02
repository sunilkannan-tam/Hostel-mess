import os
import uvicorn

if __name__ == '__main__':
    # HOST defaults to 0.0.0.0 so the RFID reader, serving-counter device,
    # and any other machine on the mess-hall LAN can actually reach this
    # server. 127.0.0.1 (the old default) only accepts connections from
    # the same machine the server runs on, which breaks a real deployment
    # where the reader and the server are different devices.
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    # RELOAD defaults to off. Auto-reload is a development convenience;
    # on an always-on deployment machine it adds a file-watcher for no
    # benefit. Run this under the provided systemd unit (deploy/) or
    # deploy/start.sh for automatic restart after a crash instead.
    reload = os.getenv("RELOAD", "false").strip().lower() in {"1", "true", "yes"}
    uvicorn.run('app.main:app', host=host, port=port, reload=reload)
