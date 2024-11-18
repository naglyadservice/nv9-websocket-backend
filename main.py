import asyncio
import json
import logging
import os
from typing import Any

import aiomysql
import sentry_sdk
import websockets
from websockets import WebSocketServerProtocol

from app.event_handlers import (
    handle_hello_msg,
    handle_payment,
    handle_fiscalization,
    handle_input,
)
from app.connections import connections_handler
from app.monitors import device_ping_monitor, offline_deivces_monitor
from app.repository import Repository

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger("main")

sentry_sdk.init(
    dsn="https://551d2197d8f86754723259d7f6150c57@o4505647719448576.ingest.us.sentry.io/4507520417529856",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)

connections: dict[Any, WebSocketServerProtocol] = dict()
offline_devices: dict[str, tuple[str]] = dict()


async def websocket_handler(
    websocket: WebSocketServerProtocol, path, repository: Repository
):
    try:
        async for message in websocket:
            try:
                data: dict = json.loads(message)
            except json.JSONDecodeError:
                logger.error(f"Received invalid JSON: {message}")

            if data.get("command") == "hello":
                await handle_hello_msg(
                    data=data,
                    connections=connections,
                    websocket=websocket,
                    offline_devices=offline_devices,
                )
            elif "payment" in data:
                await handle_payment(
                    data=data, repository=repository, websocket=websocket
                )
            elif "sales" in data:
                await handle_fiscalization(
                    data=data, repository=repository, websocket=websocket
                )
            elif "input" in data:
                await handle_input(data=data, repository=repository)

            else:
                await websocket.send(
                    json.dumps(
                        {"response": "ERROR", "message": "Invalid message contnet"}
                    )
                )

    except websockets.exceptions.ConnectionClosedOK:
        pass

    except websockets.exceptions.ConnectionClosedError:
        logger.info("Connection closed")

    except Exception as e:
        logger.error(f"Unexpected error: {e.__class__.__name__}: {e}")


async def main():
    pool = await aiomysql.create_pool(
        **{
            "host": os.getenv("DB_HOST"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "db": os.getenv("DB_NAME"),
            "autocommit": True,
        }
    )
    repository = Repository(pool)

    server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, path, repository),
        os.getenv("WS_HOST"),
        os.getenv("WS_PORT"),
    )
    logger.info("WebSocket server started on port 4715")

    await asyncio.gather(
        server.wait_closed(),
        connections_handler(connections=connections, repository=repository),
        device_ping_monitor(
            connections=connections,
            repository=repository,
            ping_interval=int(os.getenv("PING_INTERVAL", 90)),
        ),
        offline_deivces_monitor(
            offline_devices=offline_devices,
            repository=repository,
            offline_interval=int(os.getenv("OFFLINE_INTERVAL", 1)),
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
