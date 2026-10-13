# Jizhile · WeChat Official Accounts and Channels MCP Plugin

[简体中文](README.md) | **English**

A budget-aware MCP plugin for Codex and compatible agents. Query WeChat Official Accounts, articles, and Channels through Jizhile's third-party API, with pricing comparisons, balance notices, and spending guards. The catalog covers 50 documented operations; only the article and video search flows have been verified against the live service.

- [Provider website](https://www.jzl.com/)
- [Official API documentation](https://s.apifox.cn/410674f9-f451-4b4f-957a-5f54f243bc83)
- API host: `https://www.dajiala.com`. This is an independent community client.

## Features

Search accounts, articles, and videos; retrieve account profiles, ownership information, publishing history, article content, engagement metrics, comments, Channel posts, replay records, and download links. Provider response fields are preserved alongside a billing summary. Download-link queries do not download media.

## Install and configure

Requires Python 3.11+ and uv. Install in Codex from GitHub:

```sh
codex plugin marketplace add guangfuhao/jizhile-mcp
codex plugin add jizhile-mcp@jizhile-local
```

Configure your own API Key through the agent's `jizhile_setup_local` tool. It opens a temporary setup page on `127.0.0.1`, saves credentials locally, and exits after saving or timing out. The default file is `~/.config/jizhile-mcp/credentials.json`, with mode `0600`. API Keys are never bundled with this repository or releases.

For development or terminal configuration:

```sh
git clone https://github.com/guangfuhao/jizhile-mcp.git
cd jizhile-mcp
uv sync --frozen --extra dev
uv run jizhile-configure
```

The terminal prompts hide the Key and optional verification code. Environment variables `JIZHILE_API_KEY`, `JIZHILE_VERIFYCODE`, and `JIZHILE_CONFIG_FILE` are also supported. Settings tools always mask the Key.

To install a local checkout, run `python3 scripts/package_plugin.py`, then add the checkout's absolute path as a Codex marketplace and install `jizhile-mcp@jizhile-local`. Other MCP clients can use `mcp.json`, replacing `${PLUGIN_ROOT}` with the plugin's absolute path.

## Billing and budget safeguards

1. Use `jizhile_balance` to inspect balance and budgets, `jizhile_compare` to compare suitable routes, and `jizhile_catalog` for parameters.
2. Obtain a quote using `jizhile_quote_search` or `jizhile_quote`. Quotes expire after ten minutes. The agent must disclose the expected/reserved charge, pricing basis, current balance, and projected remaining balance before execution.
3. Execute only within the user's authorized scope and budget using `jizhile_execute(quote_id, confirm_charge=true)`. Example or unknown prices require an explicit user-supplied reservation and acceptance of price uncertainty.
4. Report the actual charge and latest balance. Unknown charges must be reported as pending reconciliation, never as zero.

Default limits are **CNY 10 per request, CNY 500 per day, and a CNY 100 balance reserve**. Daily accounting uses Asia/Shanghai time. A paid request's projected remaining balance must be at least CNY 100: for example, a CNY 0.50 query is allowed at a balance of CNY 100.50, while a balance below CNY 100 blocks new paid requests.

Existing environment overrides still take precedence: `JIZHILE_SINGLE_LIMIT`, `JIZHILE_DAILY_LIMIT`, and `JIZHILE_BALANCE_RESERVE`. Change them only with the user's authorization. Query parameters cannot raise these limits.

Instances using the same Key share a private SQLite ledger and serialize paid requests across processes. Each quote can execute only once. Reservations persist before network submission, so an interrupted request remains pending reconciliation. Successful results are cached for five minutes with their age; a cache hit adds no business-query charge. Use `fresh=true` only when a refresh is needed.

There are no automatic retries, pagination, or upgrades to more expensive endpoints. Error responses are also checked for charges. Timeouts, missing charge fields, or charges above the reservation block further paid calls. Only after the user checks the provider's bill and supplies the actual charge may `jizhile_reconcile` resolve that record.

**The provider has no documented maximum-charge parameter. Local budgets cannot guarantee that a single upstream request will never exceed its estimate, or restrict spending by other clients using the same Key. The plugin stops subsequent paid requests after detecting a billing anomaly.** Do not delete the ledger to bypass limits.

## Choosing an economical route

The following distinctions come from documentation read on 2026-10-13. Documented rates and example response charges are separate; actual provider billing is authoritative.

| Need | Options and pricing basis |
|---|---|
| Find Official Accounts | Live account search: CNY 1/request. Database search: CNY 0.20/item, with 20 items per page, potentially CNY 4/page. A smaller `size` has not been verified to reduce returned items, so at least CNY 4 is reserved. |
| Search articles | Both documented article search routes cost CNY 0.50/request; select the required sorting, date filters, and fields. |
| Search videos | All-results video search costs CNY 0.50/request; video-category search costs CNY 1/request. Prefer the cheaper route when it meets the need. |
| Locate one Channel by exact name | The ID lookup response example shows CNY 0.20; account search is documented at CNY 1/request. Their scope differs, and the example is not a guaranteed rate. |
| Article content | HTML, Pro, text/rich-text, and video-enabled detail examples show CNY 0.02, 0.025, 0.03, and 0.10. Outputs differ and these examples are not confirmed tariffs. |
| Article engagement | Basic and Pro response examples show CNY 0.02 and 0.04; basic fields do not require an automatic Pro upgrade. |

Reuse existing identifiers, list fields, and cached results before searching or converting IDs again. Today's publishing window and historical lists are different products. Database follower figures are estimates rather than precise live counts.

## Tools and usage

The plugin exposes `jizhile_settings`, `jizhile_setup_local`, `jizhile_balance`, `jizhile_catalog`, `jizhile_compare`, `jizhile_quote_search`, `jizhile_quote`, `jizhile_execute`, and `jizhile_reconcile`.

Example requests:

- “Search one page of People's Daily articles with a maximum budget of CNY 0.50. Show the charge and balance first.”
- “Find videos about Beijing housing. Compare prices and use at most one page within a CNY 1 budget.”
- “Compare article-content endpoint prices without submitting a paid query.”

Long IDs must be strings to avoid JavaScript integer precision loss. The catalog and source links are in `src/jizhile_mcp/catalog.json` and `docs/sources.json`. Document inconsistencies are noted in the catalog; for example, Channel video search uses `BusinessType=7` from the request example despite a conflicting field description.

## Verification and releases

```sh
uv run --frozen pytest -q
uv run --frozen python scripts/mcp_smoke.py
```

The default smoke test loads the MCP catalog and comparison tool without paid business queries. `--live` explicitly enables at most two first-page business queries, documented at CNY 1 total, subject to configured budgets and the balance reserve. Live receipts contain personal balance fields; remove them before publishing.

A historical live MCP acceptance run on 2026-10-13 returned 15 articles and 12 videos for the query “人民日报”, with titles, IDs, and links checked. Each first-page query cost CNY 0.50; duplicate queries were served from cache with zero additional business-query charge. See the [sanitized receipt](docs/live-test-receipt.json). Other operations have not been individually tested against paid live endpoints. This receipt predates the new default limits.

`bundle/` is the generated, installable plugin directory. After changing source files, run `python3 scripts/package_plugin.py` and commit the generated files; CI verifies that the bundle matches the source. CI uses mocks and non-billing MCP checks with no real Key configured.

Keys, verification codes, local configuration, caches, and billing ledgers are excluded from releases. Run `python3 scripts/check_secrets.py`; local maintainers can add `--local-config` to compare locally stored secret values against source files, Git history, and release archives without printing the secrets.
