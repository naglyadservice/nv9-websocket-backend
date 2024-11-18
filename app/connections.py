import asyncio
from logging import Logger, getLogger
from typing import Any

import websockets
from app.repository import Repository


logger: Logger = getLogger("connections")


async def connections_handler(connections: dict, repository: Repository) -> None:
    while True:
        for factory_number, websocket in list(connections.items()):
            if websocket.closed:
                try:
                    await websocket.close()
                    logger.info(f"Closed connection for {factory_number}")
                except Exception as e:
                    logger.error(
                        f"Error closing connection for {factory_number}: {e.__class__.__name__}: {e}"
                    )
                finally:
                    connections.pop(factory_number)
                    logger.info(f"Removed closed connection for {factory_number}")

        try:
            system_messages = await repository.get_unanswered_system_messages()
            for factory_number, message in system_messages:
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
