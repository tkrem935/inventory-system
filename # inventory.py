# -*- coding: utf-8 -*-
"""
inventory.py — система учёта товаров с синхронизацией остатков
на маркетплейсы (Wildberries, Ozon, Яндекс Маркет).

Запуск: python3 inventory.py
"""

import sqlite3
import csv
import os
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None


# ──────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ──────────────────────────────────────────────

DB = Path("inventory.db")

CREDENTIALS = {
    "wb": {
        "token": os.environ.get("WB_TOKEN"),
        "warehouse_id": os.environ.get("WB_WAREHOUSE_ID"),
    },
    "ozon": {
        "client_id": os.environ.get("OZON_CLIENT_ID"),
        "api_key": os.environ.get("OZON_API_KEY"),
        "warehouse_id": os.environ.get("OZON_WAREHOUSE_ID"),
    },
    "yandex": {
        "token": os.environ.get("YM_TOKEN"),
        "business_id": os.environ.get("YM_BUSINESS_ID"),
        "warehouse_id": os.environ.get("YM_WAREHOUSE_ID"),
    },
}

STOCK_BUFFER = int(os.environ.get("STOCK_BUFFER", "0"))


# ──────────────────────────────────────────────
# РАБОТА С БАЗОЙ ДАННЫХ
# ──────────────────────────────────────────────

def init_db():
    """Создание таблиц, если их ещё нет."""
    with sqlite3.connect(DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT    NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                price    REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_mapping (
                product_id   INTEGER NOT NULL,
                marketplace  TEXT    NOT NULL,
                external_id  TEXT    NOT NULL,
                warehouse_id TEXT,
                PRIMARY KEY (product_id, marketplace),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)


def add_product(name, quantity, price):
    """Добавить товар. Возвращает id записи."""
    if quantity < 0 or price < 0:
        raise ValueError("quantity и price должны быть >= 0")
    with sqlite3.connect(DB) as conn:
        cursor = conn.execute(
            "INSERT INTO products (name, quantity, price) VALUES (?, ?, ?)",
            (name, quantity, price),
        )
        return cursor.lastrowid


def get_product(product_id):
    """Получить товар по id. Возвращает (id, name, quantity, price) или None."""
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT id, name, quantity, price FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()


def list_products():
    """Список всех товаров: [(id, name, quantity, price), ...]"""
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT id, name, quantity, price FROM products ORDER BY id"
        ).fetchall()


def update_product(product_id, quantity=None, price=None):
    """Обновить остаток и/или цену. None — оставить без изменений."""
    with sqlite3.connect(DB) as conn:
        if quantity is not None:
            conn.execute(
                "UPDATE products SET quantity = ? WHERE id = ?",
                (quantity, product_id),
            )
        if price is not None:
            conn.execute(
                "UPDATE products SET price = ? WHERE id = ?",
                (price, product_id),
            )


def delete_product(product_id):
    """Удалить товар и все его привязки к маркетплейсам."""
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM marketplace_mapping WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


def add_mapping(product_id, marketplace, external_id, warehouse_id=None):
    """
    Привязать товар к карточке на маркетплейсе.

    :param marketplace:  'wb', 'ozon' или 'yandex'
    :param external_id:  WB — chrtId, Ozon — offer_id, Яндекс — shopSku
    :param warehouse_id: ID склада на маркетплейсе
    """
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO marketplace_mapping "
            "(product_id, marketplace, external_id, warehouse_id) "
            "VALUES (?, ?, ?, ?)",
            (product_id, marketplace, external_id, warehouse_id),
        )


# ──────────────────────────────────────────────
# ОТЧЁТЫ
# ──────────────────────────────────────────────

def stock_report():
    """Полный отчёт: [(name, quantity, price, total_value), ...]"""
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT name, quantity, price, quantity * price FROM products ORDER BY id"
        ).fetchall()


def low_stock_report(threshold=5):
    """Товары с остатком ниже порога: [(name, quantity), ...]"""
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT name, quantity FROM products WHERE quantity < ? ORDER BY quantity",
            (threshold,),
        ).fetchall()


# ──────────────────────────────────────────────
# ИМПОРТ / ЭКСПОРТ CSV
# ──────────────────────────────────────────────

def import_csv(filepath):
    """
    Импорт товаров из CSV. Заголовок: name,quantity,price
    Кодировка UTF-8. Дубликаты не проверяются — каждый раз вставка новой строки.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {filepath}")

    added = 0
    with sqlite3.connect(DB) as conn:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row["name"].strip()
                quantity = int(row["quantity"])
                price = float(row["price"])
                conn.execute(
                    "INSERT INTO products (name, quantity, price) VALUES (?, ?, ?)",
                    (name, quantity, price),
                )
                added += 1
    print(f"Импортировано {added} товаров из {filepath}")
    return added


def export_csv(filename="report.csv"):
    """Экспорт всех товаров в CSV (UTF-8)."""
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("SELECT id, name, quantity, price FROM products").fetchall()

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "quantity", "price"])
        writer.writerows(rows)
    print(f"Экспортировано {len(rows)} товаров в {filename}")


# ──────────────────────────────────────────────
# КЛИЕНТЫ МАРКЕТПЛЕЙСОВ
# ──────────────────────────────────────────────

WB_API_URL = "https://marketplace-api.wildberries.ru"
OZON_API_URL = "https://api-seller.ozon.ru"
YM_API_URL = "https://api.partner.market.yandex.ru"


def _check_requests():
    if requests is None:
        raise RuntimeError(
            "Библиотека requests не установлена.\n"
            "Установи:  pip install requests"
        )


def update_wb_stocks(token, warehouse_id, stocks):
    """
    Обновление остатков на Wildberries.
    stocks: [{"sku": chrtId, "amount": кол-во}, ...]
    Лимит: не чаще 1 запроса в 30 секунд на один склад.
    """
    _check_requests()
    url = f"{WB_API_URL}/api/v3/stocks/{warehouse_id}"
    headers = {"Authorization": token, "Content-Type": "application/json"}

    for attempt in range(3):
        resp = requests.put(url, json={"stocks": stocks}, headers=headers)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 30))
            print(f"  WB: превышен лимит, ждём {wait} сек…")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()

    raise RuntimeError("WB: не удалось обновить остатки после 3 попыток")


def update_ozon_stocks(client_id, api_key, warehouse_id, stocks):
    """
    Обновление остатков на Ozon.
    stocks: [{"offer_id": артикул, "stock": кол-во}, ...]
    Лимит: до 100 товаров за запрос, до 80 запросов в минуту.
    """
    _check_requests()
    url = f"{OZON_API_URL}/v2/products/stocks"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "stocks": [
            {
                "offer_id": s["offer_id"],
                "stock": s["stock"],
                "warehouse_id": warehouse_id,
            }
            for s in stocks
        ]
    }

    for attempt in range(3):
        resp = requests.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            print("  Ozon: превышен лимит, ждём 5 сек…")
            time.sleep(5)
            continue
        resp.raise_for_status()
        return resp.json()

    raise RuntimeError("Ozon: не удалось обновить остатки после 3 попыток")


def update_yandex_stocks(token, business_id, warehouse_id, stocks):
    """
    Обновление остатков на Яндекс Маркете.
    stocks: [{"sku": shopSku, "count": кол-во}, ...]
    """
    _check_requests()
    url = f"{YM_API_URL}/v3/businesses/{business_id}/offers/stocks/update"
    headers = {
        "Authorization": f"OAuth {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "warehouseId": warehouse_id,
        "offers": [{"sku": s["sku"], "count": s["count"]} for s in stocks],
    }

    for attempt in range(3):
        resp = requests.post(url, json=payload, headers=headers)
        if resp.status_code == 420:
            remaining = resp.headers.get("X-RateLimit-Resource-Until")
            wait = int(remaining) if remaining else 30
            print(f"  Яндекс Маркет: превышен лимит, ждём {wait} сек…")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()

    raise RuntimeError("Яндекс Маркет: не удалось обновить остатки после 3 попыток")


# ──────────────────────────────────────────────
# СИНХРОНИЗАЦИЯ: БАЗА → МАРКЕТПЛЕЙС
# ──────────────────────────────────────────────

def sync_stocks_to_marketplace(marketplace):
    """
    Выгрузить остатки из базы на маркетплейс.
    marketplace: 'wb', 'ozon' или 'yandex'
    """
    creds = CREDENTIALS.get(marketplace)
    if not creds:
        print(f"Неизвестный маркетплейс: {marketplace}")
        return

    if marketplace == "wb" and not creds.get("token"):
        print("WB_TOKEN не задан. Установи переменную окружения:")
        print("  export WB_TOKEN='твой_токен'")
        return
    if marketplace == "ozon" and not (creds.get("client_id") and creds.get("api_key")):
        print("OZON_CLIENT_ID и/или OZON_API_KEY не заданы.")
        print("  export OZON_CLIENT_ID='твой_client_id'")
        print("  export OZON_API_KEY='твой_api_key'")
        return
    if marketplace == "yandex" and not creds.get("token"):
        print("YM_TOKEN не задан. Установи переменную окружения:")
        print("  export YM_TOKEN='твой_oauth_токен'")
        return

    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            """SELECT mm.external_id, mm.warehouse_id, p.quantity
               FROM marketplace_mapping mm
               JOIN products p ON mm.product_id = p.id
               WHERE mm.marketplace = ?""",
            (marketplace,),
        ).fetchall()

    if not rows:
        print(f"Нет товаров, привязанных к {marketplace}.")
        print("Используй add_mapping(product_id, marketplace, external_id, warehouse_id)")
        return

    by_warehouse = {}
    for external_id, warehouse_id, quantity in rows:
        send_qty = max(0, quantity - STOCK_BUFFER)
        by_warehouse.setdefault(warehouse_id, []).append({
            "external_id": external_id,
            "quantity": send_qty,
        })

    total_sent = 0
    for warehouse_id, items in by_warehouse.items():
        wh = warehouse_id or creds.get("warehouse_id")
        if not wh:
            print(f"Не указан warehouse_id для {marketplace}. Пропуск.")
            continue

        if marketplace == "wb":
            stocks = [{"sku": int(i["external_id"]), "amount": i["quantity"]} for i in items]
            update_wb_stocks(creds["token"], wh, stocks)

        elif marketplace == "ozon":
            stocks = [{"offer_id": str(i["external_id"]), "stock": i["quantity"]} for i in items]
            update_ozon_stocks(
                creds["client_id"], creds["api_key"], wh, stocks
            )

        elif marketplace == "yandex":
            stocks = [{"sku": str(i["external_id"]), "count": i["quantity"]} for i in items]
            update_yandex_stocks(
                creds["token"], creds["business_id"], wh, stocks
            )

        total_sent += len(items)
        print(f"  {marketplace} / склад {wh}: отправлено {len(items)} позиций")

    print(f"Синхронизация {marketplace} завершена. Всего отправлено: {total_sent} позиций.")


# ──────────────────────────────────────────────
# ДЕМО-РЕЖИМ
# ──────────────────────────────────────────────

def demo():
    """Тест без обращения к API: создаёт БД, добавляет товары, показывает отчёты."""
    print("=== Демо-режим: проверка локальной базы ===\n")

    init_db()
    print("[1] База инициализирована:", DB.resolve())

    pid1 = add_product("Товар A", 50, 1990.0)
    pid2 = add_product("Товар B", 3, 4500.0)
    pid3 = add_product("Товар C", 18, 790.0)
    print(f"[2] Добавлены товары: id={pid1}, {pid2}, {pid3}")

    add_mapping(pid1, "wb", "100001", "123456")
    add_mapping(pid1, "ozon", "SKU-A-001", "2345678900000")
    add_mapping(pid2, "wb", "100002", "123456")
    add_mapping(pid3, "yandex", "SKU-C-001", "345678")
    print("[3] Товары привязаны к маркетплейсам (тестовые ID)")

    update_product(pid2, quantity=2)
    print(f"[4] Остаток товара id={pid2} обновлён до 2")

    print("\n--- Отчёт по всем товарам ---")
    print(f"{'Название':<25} {'Кол-во':>6} {'Цена':>8} {'Сумма':>10}")
    for name, qty, price, total in stock_report():
        print(f"{name:<25} {qty:>6} {price:>8.0f} {total:>10.0f}")

    print("\n--- Товары с низким остатком (< 5) ---")
    low = low_stock_report(threshold=5)
    if low:
        for name, qty in low:
            print(f"  {name}: {qty} шт.")
    else:
        print("  Все товары в достатке.")

    export_csv("report.csv")
    print(f"\n[7] Отчёт экспортирован в report.csv")

    print("\n--- Синхронизация с маркетплейсами ---")
    print("В демо-режиме реальные API не вызываются.")
    print("Чтобы запустить синхронизацию, задай токены и вызови:")
    print("  sync_stocks_to_marketplace('wb')")
    print("  sync_stocks_to_marketplace('ozon')")
    print("  sync_stocks_to_marketplace('yandex')")
    print()

    sync_stocks_to_marketplace("wb")

    print("\n=== Демо завершено ===")
    print("База данных:", DB.resolve())
    print("CSV-отчёт:   report.csv")


if __name__ == "__main__":
    demo()
