from multiprocessing import cpu_count
from os import getenv

accesslog = "-"
bind = "0.0.0.0:5000"
capture_output = True
enable_stdio_inheritance = True
graceful_timeout = 3000
limit_request_line = 0
loglevel = "debug"
preload_app = True
raw_env = ["TERM=screen"]
timeout = 3000
workers = 2 * cpu_count() + 1 if getenv("REDIS_ADDR") else 1


def post_fork(server, worker):
    if preload_app:
        from eNMS.database import db

        db.engine.dispose()
