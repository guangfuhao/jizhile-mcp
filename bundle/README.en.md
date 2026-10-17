# Jizhile · Media and Commerce MCP Plugin

[简体中文](README.md) | **English**

A budget-aware MCP plugin for Codex and compatible agents. Query WeChat Official Accounts, articles, and Channels through Jizhile's third-party API, with pricing comparisons, balance notices, and spending guards. The expanded catalog contains 303 entries, including 291 documented operations and 12 retained legacy paths; only the article and video search flows in that catalog have been verified live. The integrated audio transcription flow has a separate three-video acceptance receipt below.

- [Provider website](https://www.jzl.com/)
- [Official API documentation](https://s.apifox.cn/410674f9-f451-4b4f-957a-5f54f243bc83)
- API host: `https://www.dajiala.com`. This is an independent community client.

## All-media and commerce APIs

All 241 operations in the [new Cloud Point documentation](https://s.apifox.cn/6faad22e-3ea1-4934-8926-69d0efb2dce1/llms.txt) are represented by request adapters, alongside the original 50 WeChat operations: 291 documented operations, including two balance probes. The catalog also retains 12 workbook paths absent from the new docs, for a total of 303 entries. Two Xingtu operations remain disabled because the supplied tariff sheet marks them unavailable. There are 289 documented, non-disabled operations including both balance probes; this is not a claim of individual paid live acceptance. See the [coverage report](docs/tariff-coverage.md).

Cloud Point requests use `https://api.yddm.com` and a separate `X-API-Key`. Use `jizhile_setup_local(provider="yddm")` or `uv run jizhile-configure-yddm` to configure it locally. The key is stored in `~/.config/jizhile-mcp/yddm-credentials.json` with mode 0600. Original Jizhile and Ark keys are never reused automatically.

Confirm the units per CNY for both business `data.cost/data.balance` and profile `data.balance_cents`. The UI's reference value of 1000 comes from comparing the documented 100 points with the workbook's CNY 0.1; verify both conversions in the account console before checking the confirmation box. The field name alone does not establish cents. Unconfirmed units block paid quotes, while the profile probe can return a raw balance. Environment overrides: `JIZHILE_YDDM_API_KEY`, `JIZHILE_YDDM_CONFIG_FILE`, `JIZHILE_YDDM_UNITS_PER_YUAN`, `JIZHILE_YDDM_BALANCE_UNITS_PER_YUAN`, and `JIZHILE_YDDM_UNITS_CONFIRMED=true`.

Use `jizhile_catalog` with platform category, keyword, offset and limit; inspect an endpoint for its schema, required fields, enums and source. `callable_only=true` filters documented, non-disabled entries. Compare arbitrary candidate IDs with `jizhile_compare(intent="custom", candidates=[...])`. Quotes select the provider automatically; `yddm:` quote IDs route through the existing execution tool. There are still 16 MCP tools in the same plugin.

Jizhile and Cloud Point queries share a **CNY 500 daily total**, with a CNY 10 single-request cap and a separate CNY 100 reserve in each account. Shared locking and aggregation apply within the same state root across keys/processes; Ark transcription remains separate. Account balances are not pooled. Async submission, status, result and acceptance steps each require their own quote; there is no automatic polling or retry.

Parameters follow the OpenAPI JSON schemas, including arrays, objects, nulls and string-safe long IDs. Six empty or incorrect schemas are filled from explicit same-page request examples; additional schema/example corrections appear in `contract_notes`. No example targets are supplied implicitly. PDD result lookup is corrected to `GET /pdd/async_get_comment_task`, with its documented JSON body.

The dated tariff snapshot preserves all 290 source records. Conditional rates use the higher tier; conflicts use the higher reservation. `tariff_snapshot`, `tariff_range`, `tariff_conflict`, and `unknown` require an explicit cap and acceptance of uncertainty. Confirmed point-to-CNY conversions with a documented point rate use `documented_points`. Changes invalidate quotes; unit changes against an existing billing ledger block further paid requests pending an accounting review. Missing costs, overruns and network failures remain uncertain and never trigger an automatic retry.

330 automated tests passed, including mocked HTTP roundtrips for 238 non-disabled Cloud Point business operations. A real key verified authentication, balance retrieval, and the reserve guard. The account balance was below the configured reserve, so **no real paid Cloud Point business request was submitted**. See the [sanitized receipt](docs/cloud-test-receipt.json); profile access is not business-data acceptance.

## Features

Search accounts, articles, and videos; retrieve account profiles, ownership information, publishing history, article content, engagement metrics, comments, Channel posts, replay records, and download links. Provider response fields are preserved alongside a billing summary. Download-link queries do not download media.

## Video speech transcription in the same plugin

The `jizhile-transcription` skill is integrated into this existing plugin. It downloads authorized video links locally, extracts audio with ffmpeg, and calls Volcengine Ark to transcribe actual speech. It supports XLSX/CSV/JSON lists and local `video_path` inputs, up to 500 items, sequential processing, segmentation, background progress, cancellation, and resumable results. It does not turn titles into transcripts or perform subtitle OCR.

Install ffmpeg and ffprobe (`brew install ffmpeg` on macOS). Configure a separate Ark Key with `jizhile_transcription_setup_local` or hidden terminal input:

```sh
uv run jizhile-configure-ark
uv run jizhile-transcribe /absolute/path/videos.xlsx --ids 1,2,45
uv run jizhile-transcribe --resume BATCH_ID --max-budget-yuan 1 --confirm-charge --accept-balance-unavailable
uv run jizhile-transcribe --status BATCH_ID
```

The list command only prepares a batch and estimates its reservation. The resume command explicitly authorizes transcription within a total budget. The default model is `doubao-seed-2-0-mini-260428`, cheaper at the checked reference rates than the supported Lite model. Audio is converted to mono 16kHz, 48kbps MP3, segmented at 180 seconds, and submitted as Base64. Temporary video/audio files are removed after processing; TXT files and `results.json` retain text, source rows, item states, segments, and token usage. The input workbook is unchanged.

Ark credentials are stored separately in `~/.config/jizhile-mcp/ark-credentials.json` with mode `0600`. Environment overrides: `JIZHILE_ARK_API_KEY`, `ARK_API_KEY`, and `JIZHILE_ARK_CONFIG_FILE`. **This runtime Key does not provide a verified Ark account balance in this workflow. Ark balance and the actual bill are explicitly unknown; Jizhile's balance or its CNY 100 reserve must not be presented as Ark's balance protection.** Each batch needs an explicit total budget and acceptance of billing with an unavailable balance. Per-request CNY 10 and daily CNY 500 guards still apply before each model request, subject to environment overrides.

Transcription charges are estimates from returned token usage and [published reference rates](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh), not settled bills. For input contexts up to 32K, rates checked on 2026-10-13 are Mini text/audio/output CNY 0.2/3/2 per million tokens, and Lite CNY 0.6/9/3.6. Reservations include an output cap and headroom. Incomplete output, uncertain charges, over-reservation estimates, and forced interruption stop subsequent calls. No automatic retries or paid link refreshes occur. Completed results and identical audio chunks can be reused.

Automatic transcription can misrecognize names, places, or amounts; review those fields. There is no unsolicited rewriting or factual correction, and chunk times are not word-level subtitle alignment. See the [sanitized three-video acceptance receipt](docs/transcription-test-receipt.json); source media, transcripts, signed URLs, and credentials are not published.

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

Integrated transcription tools: `jizhile_transcription_settings`, `jizhile_transcription_setup_local`, `jizhile_transcription_prepare`, `jizhile_transcription_run`, `jizhile_transcription_status`, `jizhile_transcription_cancel`, and `jizhile_transcription_reconcile`.

Example requests:

- “Search one page of People's Daily articles with a maximum budget of CNY 0.50. Show the charge and balance first.”
- “Find videos about Beijing housing. Compare prices and use at most one page within a CNY 1 budget.”
- “Compare article-content endpoint prices without submitting a paid query.”

Consult current quote metadata and the dated tariff snapshot before relying on any historical rate above. Long IDs must be strings to avoid JavaScript integer precision loss. Original contracts, cloud contracts and tariffs are in `src/jizhile_mcp/catalog.json`, `cloud_contracts.json` and `tariff_snapshot.json`; provenance and coverage are in `docs/sources.json` and `docs/tariff-coverage.json`. Document inconsistencies are noted in the catalog; for example, Channel video search uses `BusinessType=7` from the request example despite a conflicting field description.

## Verification and releases

```sh
uv run --frozen pytest -q
uv run --frozen python scripts/mcp_smoke.py
```

The default smoke test loads the MCP catalog and comparison tool without paid business queries. `--live` explicitly enables at most two first-page business queries, documented at CNY 1 total, subject to configured budgets and the balance reserve. Live receipts contain personal balance fields; remove them before publishing.

A historical live MCP acceptance run on 2026-10-13 returned 15 articles and 12 videos for the query “人民日报”, with titles, IDs, and links checked. Each first-page query cost CNY 0.50; duplicate queries were served from cache with zero additional business-query charge. See the [sanitized receipt](docs/live-test-receipt.json). Other operations have not been individually tested against paid live endpoints. This receipt predates the new default limits.

`bundle/` is the generated, installable plugin directory. After changing source files, run `python3 scripts/package_plugin.py` and commit the generated files; CI verifies that the bundle matches the source. CI uses mocks and non-billing MCP checks with no real Key configured.

Keys, verification codes, local configuration, caches, and billing ledgers are excluded from releases. Run `python3 scripts/check_secrets.py`; local maintainers can add `--local-config` to compare locally stored secret values against source files, Git history, and release archives without printing the secrets.
