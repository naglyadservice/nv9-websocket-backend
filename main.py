import asyncio
import hashlib
import json
import logging
import os
import time
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from typing import Any

import aiomysql
import sentry_sdk
import websockets
from websockets import WebSocketServerProtocol
from aiogram import Bot

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

sentry_sdk.init(
    dsn="https://551d2197d8f86754723259d7f6150c57@o4505647719448576.ingest.us.sentry.io/4507520417529856",
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    traces_sample_rate=1.0,
    # Set profiles_sample_rate to 1.0 to profile 100%
    # of sampled transactions.
    # We recommend adjusting this value in production.
    profiles_sample_rate=1.0,
)
# Use environment variables for sensitive information
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "db": os.getenv("DB_NAME"),
    "autocommit": True,
}

connections: dict[Any, WebSocketServerProtocol] = dict()
offline_devices: dict[str, str] = dict()

bot = Bot(os.getenv("BOT_TOKEN"))


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


async def insert_fiskalization(pool, factory_number, sales_code, sales_cash, created_at):
    async with pool.acquire() as conn, conn.cursor() as cur:
        try:
            await cur.execute(
                """
                SELECT 1
                FROM fiskalization_table
                WHERE factory_number = %s 
                    AND sales_code = %s
                    AND date >= NOW() - INTERVAL 1 MINUTE
                """,
                (factory_number, sales_code),
            )
            exists = await cur.fetchone()
            if exists:
                logger.info(f"Duplicate fiskalization for {factory_number} with code {sales_code}")
                return True
            
            await cur.execute(
                """
                INSERT INTO `fiskalization_table` (factory_number, sales_code, sales_cashe, date_msg)
                VALUES (%s, %s, %s, %s)
                """,
                (factory_number, sales_code, sales_cash, created_at),
            )
            return True
        except Exception as e:
            logger.error(f"Error inserting fiskalization: {e.__class__.__name__}: {e}")
            return False


async def system_messages_handler(pool):
    while True:
        # Implement connection cleanup
        to_close: list[tuple[WebSocketServerProtocol, Any]] = []
        for fn, ws in connections.copy().items():
            if ws.closed:
                connections.pop(fn)
                to_close.append((ws, fn))
                logger.info(f"Removed closed connection for {fn}")

        for ws, fn in to_close:
            try:
                await ws.close()
                logger.info(f"Closed connection for {fn}")
            except Exception as e:
                logger.error(
                    f"Error closing connection for {fn}: {e.__class__.__name__}: {e}"
                )

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
                            ws = connections.pop(factory_number)
                            await ws.close()

        except Exception as e:
            logger.exception(
                f"Error in system_messages_handler: {e.__class__.__name__}: {e}"
            )

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
                    if factory_number in offline_devices:
                        try:
                            await bot.send_message(
                                offline_devices[factory_number],
                                f"Устройство {factory_number} возобновило соединение"
                            )  
                        except Exception:
                            logger.error(
                                f"Error while sending message about {factory_number} device"
                            )
                        offline_devices.pop(factory_number)
                        
                elif "payment" in data:
                    payment = "PAID" if "paid" in data["payment"] else data["payment"]
                    factory_number = data["factory_number"]
                    logger.info(f"Payment for {factory_number} is {payment}")

                    async with pool.acquire() as conn, conn.cursor() as cur:
                        await cur.execute(
                            "UPDATE system_messages SET response = %s WHERE factory_number = %s",
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
                        data["sales"]["created_at"],
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
        
        
async def device_ping_monitor(pool, ping_interval):
    """
    Monitors device connectivity using native WebSocket ping/pong frames.
    """
    
    while True:
        for fn, ws in connections.copy().items():
            if ws.closed:
                continue
            
            try:
                pong_waiter = await ws.ping()
                latency = await pong_waiter
                logger.info(f"Pong recieved from {fn} device with {latency} latency")
                
                async with pool.acquire() as conn, conn.cursor() as cur:
                    try:
                        await cur.execute(
                            """
                            UPDATE devices
                            SET last_online = NOW()
                            WHERE factory_number = %s
                            """,
                            (fn,),
                        )
                    except Exception as e:
                        logger.error(f"Error inserting device last online: {e.__class__.__name__}: {e}")
                        continue
            except Exception:
                pass
                
        await asyncio.sleep(ping_interval)
        
async def offline_deivces_monitor(pool, offlite_interval):
    while True:
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 
                    devices.factory_number, 
                    users.telegram_token
                FROM devices
                JOIN users ON users.id = devices.user_id
                WHERE devices.last_online < NOW() - INTERVAL 5 %s MINUTE;
                """,
                (offlite_interval,)
            )
            results = await cur.fetchall()
        for result in results:
            if not result[1]:
                logger.warning(f"Chat wasn't found for device {result[0]}")
            else:
                await bot.send_message(
                    result[1], f"Устройство {result[0]} не в сети более {offlite_interval} минут"
                )
                offline_devices[result[0]] = offline_devices[result[1]]
                await asyncio.sleep(1)
                
        await asyncio.sleep(offlite_interval * 60)
            

async def main():
    pool = await get_db_pool()
    server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, path, pool),
        os.getenv("WS_HOST"),
        os.getenv("WS_PORT"),
    )
    logger.info("WebSocket server started on port 4715")
    await asyncio.gather(
        server.wait_closed(),
        system_messages_handler(pool),
        device_ping_monitor(pool, int(os.getenv("PING_INTERVAL", 90))),
        offline_deivces_monitor(pool, int(os.getenv("OFFLINE_INTERVAL", 5)))
    )


if __name__ == "__main__":
    asyncio.run(main())
