# Verification snapshot · 9 October 2026, Baku

Update at 19:37: customer requested removal of the separate confirmation step.
`place_order` now records immediately after checkout intent and contact details.
161 smoke checks pass, including direct checkout without any delivered summary,
session/contact validation and retry idempotency. Confirmation evidence below
describes the earlier version, whose compatibility helpers remain available.

- Base repository: Maliyev/sales-agent, commit `96343950ad6c57ff7bc2100808aa0974cd11a74f`.
- New code lives in the independent local SalesOS_dev clone.
- 159 smoke checks passed in approximately 3.2 seconds; seven inherited LIST
  behavior checks are retained and excluded. Full legacy suite was not run.
- JavaScript syntax check passed. SQLite isolation, prices, variants, stock,
  authentic explicit consent, delivery-before-consent, idempotent order creation,
  cart invalidation, authenticated Orders APIs and CSRF protections were checked.
- Retried cart additions on a superseded user turn do not double quantities.
- Live Gemini model list included `gemini-3.5-flash-lite`; generation returned OK.
- Telegram getMe authenticated the new bot: https://t.me/salesOS_demobot.
- Live elen.az search returned products and product details with real price/stock.
- Isolated live Gemini/source checkout created exactly one order for 25.55 AZN;
  repeated confirmation returned the same order. Telegram delivery in this
  scripted check was simulated by a delivered history entry, not sent via Telegram.
- Browser check used synthetic preview orders and verified desktop list on the
  right, details on the left, narrow layout and persistent status change.
- New runner is running locally. Control Panel login returned HTTP 200.
- Human Telegram conversation still needs a manual check; no public deployment.
- No wizard, AI parser engineer or knowledge chat is advertised as implemented.

Observed failures and fixes: sandbox SQLite/network restrictions required checks
outside sandbox; a search-history return regression was caught and fixed. An
initial live Russian message received an Azerbaijani reply; business language
instructions were made explicit, and a subsequent live reply used Russian.

Demo orders are requests for manual fulfillment. No payment or external elen.az
order is made. Test databases are separate from the actual bot database.
See SALESOS_README.md for setup, demonstration and reuse disclosure.
