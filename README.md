# Inventory System

Система учёта товаров и синхронизации остатков с маркетплейсами (Wildberries, Ozon, Яндекс Маркет).

**Статус:** прототип. Локальная база и отчёты работают полностью. Синхронизация с маркетплейсами — по API-токенам, подключается по одной площадке.

## Возможности

- **Учёт товаров:** добавление, обновление, удаление, отчёты по остаткам и низким остаткам.
- **Импорт/экспорт CSV:** массовая загрузка товаров и выгрузка прайс-листов.
- **Привязка к маркетплейсам:** один товар может быть на WB, Ozon и Яндексе одновременно.
- **Синхронизация остатков:** отправка актуальных количеств по API.
- **Буфер остатков:** страховочный резерв, чтобы избежать оверселла.
- **Демо-режим:** проверка работы без реальных API-запросов.

## Быстрый старт

```bash
pip install requests
python3 inventory.py

Демо создаст базу inventory.db, добавит тестовые товары и экспортирует report.csv.

Использование
Инициализация и добавление товаров

py
import inventory

inventory.init_db()
pid = inventory.add_product("Товар A", 50, 1990.0)

Привязка к маркетплейсу

py
inventory.add_mapping(pid, "wb", "100001", "123456")
inventory.add_mapping(pid, "ozon", "SKU-A-001", "2345678900000")
inventory.add_mapping(pid, "yandex", "SKU-C-001", "345678")

Обновление остатков

py
inventory.update_product(pid, quantity=10)

Синхронизация на маркетплейс

bash
export WB_TOKEN="твой_токен"
export WB_WAREHOUSE_ID="123456"

python3 -c "import inventory; inventory.sync_stocks_to_marketplace('wb')"

Импорт из CSV

CSV
name,quantity,price
Товар A,50,1990
Товар B,3,4500.5

py
inventory.import_csv("products.csv")

Токены
Wildberries - WB_TOKEN, WB_WAREHOUSE_ID - Кабинет → Настройки → Доступ к API
Ozon - OZON_CLIENT_ID, OZON_API_KEY, OZON_WAREHOUSE_ID - Настройки → API keys (ключ Admin)
Яндекс Маркет - YM_TOKEN, YM_BUSINESS_ID, YM_WAREHOUSE_ID - Настройки → API

Буфер остатков

bash
export STOCK_BUFFER=2
Если в базе 10 штук, а буфер 2 — на маркетплейс уйдёт 8.

Автоматизация (cron)

bash
*/30 * * * * cd /путь/к/проекту && WB_TOKEN="токен" WB_WAREHOUSE_ID="id" python3 -c "import inventory; inventory.sync_stocks_to_marketplace('wb')" >> sync.log 2>&1

Безопасность
Токены только в переменных окружения, не в коде.
.gitignore исключает базу, логи и .env.


