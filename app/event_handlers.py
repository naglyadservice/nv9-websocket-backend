import asyncio
import json
from logging import Logger, getLogger
import websockets

from app.bot import bot_send_message
from app.repository import Repository


logger: Logger = getLogger("handlers")

error_msg = json.dumps({"request": "ERROR"})
success_msg = json.dumps({"request": "OK"})


async def handle_hello_msg(
    data: dict,
    connections: dict,
    websocket: websockets.WebSocketServerProtocol,
) -> None:
    factory_number = data["my_factory_number"]
    connections[factory_number] = websocket
    logger.info(f"Hello from {factory_number}")


async def handle_payment(
    data: dict, repository: Repository, websocket: websockets.WebSocketServerProtocol
) -> None:
    payment = "PAID" if "paid" in data["payment"] else data["payment"]
    factory_number = data["factory_number"]
    logger.info(f"Payment for {factory_number} is {payment}")

    await repository.update_system_message_response(payment, factory_number)
    await websocket.send(success_msg)


async def handle_fiscalization(
    data: dict, repository: Repository, websocket: websockets.WebSocketServerProtocol
) -> None:
    factory_number = data["factory_number"]
    sales = data["sales"]

    # Логируем входящие данные
    logger.info(f"Received fiscalization request: {data}")

    # Используем "paypass", если он есть и больше 0, иначе "cash"
    if sales.get("paypass", 0) > 0:
        sales_cash = sales["paypass"]
        cash = 2
        logger.info(f"Using paypass: {sales_cash}")
    else:
        sales_cash = sales.get("cash", 0)
        logger.info(f"Using cash: {sales_cash}")
        
        payment_type = sales.get("payment_type")
        if payment_type == "liqpay":
            cash = 0
        elif payment_type == "cash":
            cash = 1
        elif payment_type == "paypass":
            cash = 2
        else:
            cash = 1

    logger.info(f"Determined payment type: cash={cash}, sales_cash={sales_cash}")

    if not await repository.check_device_with_fn(factory_number):
        if not await repository.check_serial_number(factory_number) or payment_type != "paypass":
            logger.warning(f"Device {factory_number} not found or invalid payment type: {payment_type}")
            await websocket.send(error_msg)
            return

    if await repository.check_recent_fiscalization(factory_number, sales["code"], 1):
        logger.warning(f"Duplicate fiscalization detected for device {factory_number} and code {sales['code']}")
        await websocket.send(error_msg)
        return

    logger.info(f"Processing fiscalization for device {factory_number}. Amount: {sales_cash}, Payment type: {cash}")

    success = await repository.add_fiscalization(
        factory_number=factory_number,
        sales_code=sales["code"],
        cash=cash,
        sales_cash=sales_cash,
        created_at=sales["created_at"],
    )

    if success:
        logger.info(f"Fiscalization successful for device {factory_number}, sales_code={sales['code']}")
    else:
        logger.error(f"Fiscalization failed for device {factory_number}, sales_code={sales['code']}")

    await websocket.send(success_msg if success else error_msg)


async def handle_input(data: dict, repository: Repository) -> None:
    factory_number = data.get("factory_number")
    input_state = data.get("input")

    # Проверяем, что данные корректны
    if not factory_number or input_state not in ["high", "low"]:
        logger.warning(f"Invalid data received: {data}")
        return

    # Получаем информацию о местоположении устройства
    chat, place = await repository.get_device_chat_and_place(factory_number)
    if not chat:
        logger.warning(f"Chat not found for device {factory_number}")
        return

    # Определяем состояние устройства
    state = "✅ Бокс зачинено 🔒" if input_state == "high" else "🚨 Бокс відчинено 🔓"

    # Формируем сообщение
    message = f"Пристрій: {factory_number}, Розшташування: {place}, Статус: {state}"

    # Отправляем сообщение в Telegram
    await bot_send_message(chat, message, factory_number)

    # Логируем информацию о состоянии
    logger.info(f"Message sent to chat {chat}: {message}")
    await asyncio.sleep(3)


