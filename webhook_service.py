#!/usr/bin/env python3
"""Entry point: `serve` runs the API, `dispatch` runs the delivery loop."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webhooks.config import Config
from webhooks.dispatcher import run_forever
from webhooks.server import serve


def main(argv):
    command = argv[1] if len(argv) > 1 else "serve"
    config = Config()

    if command == "serve":
        server = serve(config)
        print(f"webhook api on {config.bind_host}:{config.bind_port} "
              f"(db {config.db_path})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    if command == "dispatch":
        interval = int(argv[2]) if len(argv) > 2 else 30
        print(f"webhook dispatcher every {interval}s "
              f"(events {config.events_path})", flush=True)
        run_forever(config, interval=interval)
        return 0

    if command == "once":
        from webhooks import store
        from webhooks.dispatcher import run_once
        store.init_db(config.db_path)
        connection = store.connect(config.db_path)
        print(run_once(connection, config))
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
