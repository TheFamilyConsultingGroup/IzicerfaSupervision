import os
import sys

mode = os.environ.get("MODE", "web")
if mode == "web":
    os.execvp("gunicorn", ["gunicorn", "--bind", "0.0.0.0:" + os.getenv("PORT", "8080"),
                           "--workers", "1", "--threads", "4", "web:app"])
elif mode in {"setup", "relay"}:
    import relay
    relay.run(mode)
else:
    sys.exit("Mode inconnu")
