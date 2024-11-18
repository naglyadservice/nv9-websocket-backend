from logging import Logger, getLogger
import os
from aiogram import Bot


bot = Bot(os.getenv("BOT_TOKEN"))
logger: Logger = getLogger("bot")


async def bot_send_message(chat: str, message: str, device: str) -> None:
    try:
        await bot.send_message(chat, message)
    except Exception as e:
        logger.exception(
            f"Error while sendind message about {device} device: {e.__class__.__name__}: {e}"
        )
