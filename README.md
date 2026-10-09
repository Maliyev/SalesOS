# SalesOS

SalesOS is an AI shopping assistant with Telegram customer interaction and a web dashboard for managing conversations and orders.

## Live demo

Dashboard: https://salesos-production-4e28.up.railway.app/admin

Telegram bot: https://t.me/salesOS_demobot

Demo dashboard password: `admin`

## Features

- Product search with verified prices, stock and selectable variants from elen.az.
- Separate conversation history and shopping cart for each customer session.
- Add, update and remove cart items with server-side price and stock validation.
- Direct checkout after the customer requests an order and supplies name and phone.
- Orders dashboard with item details, totals, customer information and status updates.
- Editable business knowledge and agent prompts.
- Gemini integration and optional WhatsApp Cloud API support.

Adding an item to the cart does not create an order. An order appears in Orders after checkout. Orders are recorded for manual merchant fulfillment; the app does not charge payments or submit orders to an external storefront.

## Run locally

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_PASSWORD` and `ADMIN_SESSION_SECRET` in `.env`. The session secret must contain at least 32 characters. Keep credentials and databases out of Git.

```powershell
.\.venv\Scripts\python.exe -u src\runner.py
```

Local dashboard: http://127.0.0.1:8000/admin

## Demo flow

1. Ask the bot for a product.
2. Select a product and an available variant, then request a quantity for the cart.
3. Review the cart and adjust quantities if needed.
4. Request checkout and provide name, phone and optional delivery address.
5. The bot returns the recorded order ID and total.
6. Open Orders in the dashboard and inspect or update the order status.

## Configuration and deployment

Use `python -u src/runner.py` as the Railway start command. The HTTP server listens on `0.0.0.0` and the value of `PORT` when that variable is set. The domain target port must match `PORT`; the live demo uses port 8080.

Provide application credentials through Railway variables. For persistent storage, attach a volume; `RAILWAY_VOLUME_MOUNT_PATH` determines the location of `salesos.db`. `SALESOS_DATABASE_PATH` can override the database path. Local storage defaults to `data/salesos.db`.

Configure Gemini in `config.json` or with `GEMINI_MODEL`. WhatsApp is enabled only when all four WhatsApp credential values are configured.

## Checks

```powershell
python -X utf8 scripts\smoke_tests.py
python -u -X utf8 scripts\preflight.py
python -u -X utf8 scripts\live_demo_check.py
```

The live check uses a separate temporary database and does not send Telegram messages. LIST mode is disabled; its tests are excluded from the smoke suite.

## Main components

- `src/runner.py`: channel coordination and dashboard startup.
- `src/agent.py`: model calls, product search and shopping tools.
- `src/commerce.py`: carts, verified totals and recorded orders.
- `src/database.py`: SQLite persistence and session history.
- `src/admin_dashboard.py`: authenticated dashboard APIs.
- `Knowledge.md` and `prompts/`: business information and agent instructions.

## Scope

The demo does not process payments. AI Setup Engineer, an onboarding wizard, generic catalogue adapters and website customer chat are not implemented.
