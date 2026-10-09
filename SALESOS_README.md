# SalesOS · hackathon MVP

Current checkout behavior (user change at 19:35 Baku): a customer asks to
checkout and supplies name/phone; `place_order` saves immediately in Orders.
No separate confirmation message or `/confirm` command is required. Adding to
cart still does not place an order. 161 smoke checks pass. Earlier confirmation
checks below describe the initial version and retained compatibility helpers.

SalesOS adapts the existing [Maliyev/sales-agent](https://github.com/Maliyev/sales-agent)
at commit `96343950ad6c57ff7bc2100808aa0974cd11a74f`.
The prior sales pipeline, website parsers, channel adapters, SQLite history,
rate guards and Dashboard are reused components, not new hackathon work.

## Added for this competition

- Session-bound SQLite carts, variant-aware verified prices and stock.
- Integer minor-unit currency calculations and immutable order snapshots.
- Direct checkout after the customer's checkout request and contact details.
- Server verifies session ownership and rechecks prices/stock before recording.
- Idempotent checkout; repeated confirmation returns the original order.
- Control Panel Orders: scrollable list on the right, details on the left,
  customer/contact, item links and prices, status updates; Overview metrics.
- One reloadable `Knowledge.md`, editable in the existing Prompts screen.
- LIST disabled; regular search supports up to ten requests per customer turn.
- Optional WhatsApp in the combined runner; Telegram requires no Meta setup.
- Gemini model configured in `config.json` or `GEMINI_MODEL` in `.env`.

## Local setup

```powershell
cd "C:\Users\maliy\Programming\AI Hackathone 26\SalesOS_dev"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` locally: `GEMINI_API_KEY`, a NEW `TELEGRAM_BOT_TOKEN`,
`ADMIN_PASSWORD`, `ADMIN_SESSION_SECRET` (at least 32 random characters).
Do not copy the old production bot token. Keep unused WhatsApp values empty.
All four WhatsApp credential values enable its existing runner automatically.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\preflight.py
.\.venv\Scripts\python.exe -X utf8 src\runner.py
```

Control Panel: `http://127.0.0.1:8000/admin`, using `ADMIN_PASSWORD`.
The runner stores its separate database in `data/salesos.db`.
No original repository, credentials or production database are modified.

## Demo steps

1. Open the new Telegram bot and `/start`.
2. Ask for a component: “Мне нужен ESP32 для управления светодиодами”.
3. Choose an actual recommendation/variant and ask to add a quantity.
4. Ask to show the cart; change quantity or remove an item if desired.
5. Ask to checkout and provide a name, phone and optional delivery address.
6. The bot immediately records the order and returns its ID and total.
7. Refresh Control Panel → Orders. Inspect prices, quantities and customer.
8. Change status to `processing`. Retries of the same turn create no duplicate.

An order is recorded for manual fulfillment. No payment is charged and no
external elen.az order is submitted. Delivery fees are not included.
If the source cannot be rechecked, the quote/confirmation states that the
merchant must verify stock/price. Confirmed price changes block checkout.

## Verification

```powershell
python -X utf8 scripts\smoke_tests.py
node --check static/admin.js
git diff --check
```

Observed: 159 smoke tests passed, including 13 new commerce checks and existing
agent, Telegram, WhatsApp, parser, prompts and Control Panel checks.
Seven original LIST behavior tests are retained and explicitly excluded by
the smoke runner; LIST has been retired. The full legacy suite was not run.
Live `elen.az` search for ESP32 returned three results; one product detail
confirmed a price of 25.55 AZN and stock 1. These are related search results,
not proof of three exact ESP32 matches; the selection stage filters relevance.

Observed failures: sandbox prevented SQLite temporary-file access and network
requests; smoke checks passed outside that environment. A search-history return
regression introduced while adding call IDs was caught by smoke tests, fixed,
and the tests rerun successfully.

Browser checks with synthetic test orders confirmed the list/detail layout and
status update. Desktop width puts the list on the right; a narrow panel stacks
it below details. These synthetic orders are in a separate preview database.
Gemini model listing/generation and Telegram getMe succeeded for the provided
credentials. Bot: https://t.me/salesOS_demobot. A live Gemini + elen.az test in
an isolated database added an actual product, prepared checkout, saved an order
for 25.55 AZN and confirmed idempotency. Telegram delivery in that scripted test
was simulated; an actual customer conversation still requires a manual check.
Use `scripts/preflight.py` to verify the configured model is available to your
key and obtain the bot link. If a model is missing, set an available model ID
explicitly; do not assume the requested model has free quota for your account.

## Deployment and remaining scope

Deployment and public publishing require the user's instruction. No push or
production deployment has been performed. For Railway, provide variables from
`.env` and a persistent volume: the runner uses `RAILWAY_VOLUME_MOUNT_PATH` for
`salesos.db` and the existing prompt editor persists overrides on that volume.
`SALESOS_DATABASE_PATH` can explicitly override the database location.
Use `python src/runner.py` as the service start command; `PORT` controls listening.
Protect admin access with the password and session secret. Give judges the NEW
Telegram bot link once the actual conversation succeeds.

Not implemented: onboarding wizard, uploads, AI Parser Engineer, knowledge
generation/editor chat, generic new source adapters, web chat, payment processing,
public deployment and pitch deck. Existing CSV/XML/JSON sources are not advertised
as supported. This iteration prioritizes the cart/order demo before the deadline.
