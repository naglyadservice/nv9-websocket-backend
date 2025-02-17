from datetime import datetime
from logging import Logger, getLogger
from aiomysql.pool import Pool


class Repository:
    def __init__(self, pool: Pool):
        self.logger: Logger = getLogger("repository")
        self.pool = pool

    async def check_device_with_fn(self, factory_number: str) -> bool:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1
                FROM devices
                WHERE factory_number = %s
                """,
                (factory_number,)
            )
            if await cur.fetchone():
                return True
            return False
        
    async def check_serial_number(self, factory_number: str) -> bool:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1
                FROM device_serial_numbers
                WHERE serial_number = %s
                """,
                (factory_number,)
            )
            if await cur.fetchone():
                return True
            return False
        
    async def check_recent_fiscalization(
        self, factory_number: str, sales_code: str, interval: int
    ) -> bool:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1
                FROM fiskalization_table
                WHERE factory_number = %s 
                    AND sales_code = %s
                    AND date >= NOW() - INTERVAL %s MINUTE
                """,
                (factory_number, sales_code, interval),
            )
            if await cur.fetchone():
                return True
            return False

    async def add_fiscalization(
        self,
        factory_number: str,
        sales_code: str,
        sales_cash: str,
        cash: str,
        created_at: datetime,
    ) -> bool:
        try:
            async with self.pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO fiskalization_table (factory_number, sales_code, sales_cashe, cash, date_msg)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (factory_number, sales_code, sales_cash, cash, created_at),
                )
        except Exception as e:
            self.logger.error(
                f"Error inserting fiskalization: {e.__class__.__name__}: {e}"
            )
            return False
        else:
            return True

    async def update_device_last_online(self, factory_number: str) -> None:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            try:
                await cur.execute(
                    """
                    UPDATE devices
                    SET last_online = NOW()
                    WHERE factory_number = %s
                    """,
                    (factory_number,),
                )
            except Exception as e:
                self.logger.error(
                    f"Error inserting device last online: {e.__class__.__name__}: {e}"
                )

    async def get_devices_with_offline_interval(
        self, offline_interval: int
    ) -> list[tuple[str]]:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 
                    devices.factory_number,
                    devices.place_name,
                    devices.last_online,
                    users.telegram_token
                FROM devices
                JOIN users ON users.id = devices.user_id
                WHERE devices.last_online < NOW() - INTERVAL %s MINUTE;
                """,
                (offline_interval,),
            )
            return await cur.fetchall()

    async def get_unanswered_system_messages(self) -> list[tuple[str]]:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT factory_number, message FROM system_messages WHERE response IS NULL"
            )
            return await cur.fetchall()

    async def update_system_message_response(
        self, payment: str, factory_number: str
    ) -> None:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "UPDATE system_messages SET response = %s WHERE factory_number = %s",
                (payment, factory_number),
            )

    async def get_device_chat_and_place(self, factory_number: str) -> tuple[str] | None:
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT users.telegram_token, devices.place_name
                FROM users
                JOIN devices ON users.id = devices.user_id
                WHERE devices.factory_number = %s
                """,
                (factory_number,),
            )
            return await cur.fetchone()
    
    async def mark_as_fiscalized(self, factory_number: str, sales_code: str) -> bool:
        try:
            # Выполняем запрос для обновления столбца fiscalized в таблице fiskalization_table
            async with self.pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE fiskalization_table
                    SET fiscalized = 1
                    WHERE factory_number = %s AND sales_code = %s
                    """,
                    (factory_number, sales_code)
                )
                
                # Проверяем, что транзакция была обновлена
                if cur.rowcount > 0:
                    self.logger.info(f"Transaction marked as fiscalized for factory_number={factory_number}, sales_code={sales_code}")
                    return True
                else:
                    self.logger.warning(f"No transaction found for factory_number={factory_number}, sales_code={sales_code}")
                    return False
        except Exception as e:
            self.logger.error(f"Error marking transaction as fiscalized: {e.__class__.__name__}: {e}")
            return False