import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import aiomysql
import websockets
from websockets import WebSocketServerProtocol

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use environment variables for sensitive information
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "db": os.getenv("DB_NAME"),
    "autocommit": True,
}

connections: dict[Any, WebSocketServerProtocol] = {}


async def get_db_pool():
    return await aiomysql.create_pool(**DB_CONFIG)


async def check_token(token, factory_number):
    current_time = int(time.time())
    start = current_time - 10
    tokens = []

    for i in range(21):
        gen_time = start
        d = datetime.fromtimestamp(gen_time).strftime("%Y-%m-%dT%H:%M:%S")
        t = hashlib.md5(("VxI12X8u2z8#111$" + factory_number).encode()).hexdigest()
        t = hashlib.md5((t + "vpi2n2u").encode()).hexdigest()
        t = hashlib.md5((t + d).encode()).hexdigest()
        tokens.append(t)
        start += 1

    return token in tokens


async def insert_fiskalization(pool, factory_number, sales_code, sales_cash):
    async with pool.acquire() as conn, conn.cursor() as cur:
        try:
            await cur.execute(
                "INSERT INTO `fiskalization_table` (factory_number, sales_code, sales_cashe) VALUES (%s, %s, %s)",
                (factory_number, sales_code, sales_cash),
            )
            return True
        except Exception as e:
            logger.error(f"Error inserting fiskalization: {e.__class__.__name__}: {e}")
            return False


async def close_connection(factory_number, ws: WebSocketServerProtocol):
    await ws.close()
    logger.info(f"Connection closed for {factory_number}")
    del connections[factory_number]


async def system_messages_handler(pool):
    while True:
        try:
            async with pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM `system_messages` WHERE `response` IS NULL"
                )
                results = await cur.fetchall()
                for system_message in results:
                    messageID, factory_number, message = system_message[:3]
                    if factory_number in connections:
                        try:
                            logger.info(f"Check payment ready for {factory_number}")
                            await connections[factory_number].send(message)
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning(
                                f"Connection closed for {factory_number}. Removing from connections."
                            )
                            await close_connection(
                                factory_number, connections[factory_number]
                            )
                            await connections[factory_number].close()

        except Exception as e:
            logger.error(
                f"Error in system_messages_handler: {e.__class__.__name__}: {e}"
            )

        # Implement connection cleanup
        closed_connections = [fn for fn, ws in connections.items() if ws.closed]
        for fn in closed_connections:
            await close_connection(fn, connections[fn])
            del connections[fn]
            logger.info(f"Removed closed connection for {fn}")

        await asyncio.sleep(3)


async def websocket_handler(websocket: WebSocketServerProtocol, path, pool):
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("command") == "hello":
                    factory_number = data["my_factory_number"]
                    connections[factory_number] = websocket
                    logger.info(f"Hello from {factory_number}")
                elif "payment" in data:
                    payment = "PAID" if "paid" in data["payment"] else data["payment"]
                    factory_number = data["factory_number"]
                    logger.info(f"Payment for {factory_number} is {payment}")

                    async with pool.acquire() as conn, conn.cursor() as cur:
                        await cur.execute(
                            "UPDATE `system_messages` SET `response` = %s WHERE `factory_number` = %s;",
                            (payment, factory_number),
                        )
                    await websocket.send('{"request": "OK"}')
                elif "factory_number" in data:
                    factory_number = data["factory_number"]
                    logger.info(
                        f"Fiscalization from {factory_number}. Amount: {data['sales']['cash']}"
                    )

                    # Uncomment the following line to enable token checking
                    # if not await check_token(data['token'], factory_number):
                    #     await websocket.send('{"request": "ERROR", "message": "Invalid token"}')
                    #     continue

                    fisk = await insert_fiskalization(
                        pool,
                        factory_number,
                        data["sales"]["code"],
                        data["sales"]["cash"],
                    )
                    resp = '{"request": "OK"}' if fisk else '{"request": "ERROR"}'
                    await websocket.send(resp)
                else:
                    await websocket.send(
                        '{"request": "ERROR", "message": "Invalid command"}'
                    )

            except json.JSONDecodeError:
                logger.error(f"Received invalid JSON: {message}")

    except websockets.exceptions.ConnectionClosedOK:
        pass

    except websockets.exceptions.ConnectionClosedError:
        logger.info("Connection closed")


async def main():
    pool = await get_db_pool()
    server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, path, pool), os.getenv("WS_HOST"), os.getenv("WS_PORT")
    )
    logger.info("WebSocket server started on port 4715")
    await asyncio.gather(server.wait_closed(), system_messages_handler(pool))


if __name__ == "__main__":
    asyncio.run(main())
