# services/vault

Reads the Obsidian vault from disk.

- `scanner.py`: `VaultScanner.scan()` walks `VAULT_PATH` recursively in a thread-pool worker and returns a `ScanResult` (notes plus failures).
- `parser.py`: `MarkdownParser`, stateless. Extracts frontmatter, headings, `[[wikilinks]]`, tags (frontmatter and inline `#tags`), title (frontmatter > first H1 > filename) and dates.
- `models.py`: `VaultNote` (parsed note), `Heading`, `ScanResult`.
