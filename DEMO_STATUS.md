# SalesOS demo status

## Available

- Telegram customer interaction.
- Gemini-assisted product search with elen.az product details.
- Session-bound carts with selectable variants, prices, quantities and stock checks.
- Direct checkout with customer name and phone.
- Authenticated dashboard with conversations, order details and status updates.
- Configurable business knowledge and prompts.
- Railway-hosted dashboard: https://salesos-production-4e28.up.railway.app/admin.

## Verification commands

Run `python -X utf8 scripts/smoke_tests.py` for automated checks.
Run `python -u -X utf8 scripts/preflight.py` to check provider credentials and source connectivity.
Run `python -u -X utf8 scripts/live_demo_check.py` for a provider-backed cart and checkout check in an isolated database. This check sends no Telegram messages.

## Scope

Orders are recorded for manual fulfillment. No payment or external storefront order is made. AI Setup Engineer, an onboarding wizard, generic catalogue adapters and website customer chat are not implemented.
