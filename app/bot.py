import asyncio
from logging import Logger, getLogger
import os
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter


bot = Bot(os.getenv("BOT_TOKEN"))
logger: Logger = getLogger("bot")


async def bot_send_message(chat: str, message: str, device: str) -> None:
    while True:
        try:
            await bot.send_message(chat, message)
            break
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            continue   
        except Exception as e:
            logger.exception(
                f"Error while sendind message about {device} device: {e.__class__.__name__}: {e}"
            )
            break
