# TelTest Stage 09 — Content Rules

TelTest provides two independent rule layers:

1. Extraction Job Rules
2. Transfer Destination Rules

## Raw Content

`content_items.raw_text`

Raw source content is preserved and never overwritten by rules.

## Processed Content

Rule output is stored separately.

Extraction-specific state is stored in `extraction_job_items`:

- processed_text
- excluded
- rule_reason
- rules_hash
- processed_at

## Supported rules

- remove_all_links
- remove_links_containing
- exclude_text_containing
- exclude_hashtags
- exclude_links_containing
- prefix_text
- suffix_text
- prefix_link
- suffix_link

## Hashtags

Normalized hashtags are stored in:

`content_hashtags`

## Links

Extracted links and domains are stored in:

`content_links`

## Excluded content

Excluded content remains in storage.

It is excluded from new transfer plans rather than physically deleted.

## Destination rules

Every transfer destination has independent `rules_json`.

This permits different formatting and filtering for Telegram, Bale,
Eitaa and Rubika.

## Telegram Forward

Native Telegram Forward preserves the original message.

Filtering rules are supported, while content transformation applies
to Copy mode.
