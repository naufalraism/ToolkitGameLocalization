# Toolkit Game Localization & Translation

English | [Bahasa Indonesia](README.id.md)

A localization toolkit for game translators and modders. It imports text from a game's SQLite databases into a workbench with per-line status and version history, machine-translates it without breaking tags, checks quality, and builds a patched database or a single-file Unreal Engine `.pak`. It also ships a local web editor for working in a team. Python 3.10+, standard library only.

> **Status: 0.2, early.** It grew out of a personal tool for translating *Wuthering Waves* into Indonesian. The import, edit, QA, `.db` and `.pak` export, and web editor flows work and are tested. The pak output has not yet been loaded in the actual game, and only one game database (`lang_multi_text.db`) has been verified against the adapter. See [Limitations](#limitations).

## Why

Translating tens of thousands of dialogue lines produces the same problems over and over:

- Formatting tags and variables (`<color=...>`, `{0}`, `%s`) get mangled by machine translation and break the game's UI.
- The same source line is translated three different ways by three different people.
- After a game update, old translations go stale and nobody knows which lines changed.

gamelokal handles all three, and it never modifies the game's original database.

## How it works

```
game database ──import──▶ workbench.db ◀──edit / approve / revert / import-csv / web editor
                              │   ▲
                   translate ─┘   └─ import-translated (old .pak / .db / .json)
                              │
                  qa ◀────────┤
                              ▼
              export-db ──▶ patched copy of the .db      export-pak ──▶ ready-to-install .pak
```

## Quick start

```bash
pip install -e .

gamelokal inspect lang_multi_text.db                     # list tables and columns
gamelokal import lang_multi_text.db --adapter wuthering-waves --name story
gamelokal stats --by-prefix 10                           # progress per ID category
gamelokal translate --limit 50                           # LibreTranslate on localhost:5000 (free)
gamelokal search "Rover" --in source
gamelokal edit story:Intro_001 --text "Halo {0}"         # without --text, opens your editor
gamelokal history story:Intro_001                        # per-word diffs between versions
gamelokal qa --glossary examples/glossary.csv            # tags, glossary, consistency
gamelokal export-pak --base lang_multi_text.db --out MyMod_P.pak
gamelokal serve --open                                   # local web editor
```

Continue from an existing translation: `gamelokal import-translated MyOldMod_P.pak --name story --adapter wuthering-waves`.

Note: command output, error messages, and the web UI are currently in Indonesian. English localization of the tool itself is on the [roadmap](docs/RENCANA.md).

## Commands

| Command | What it does |
|---|---|
| `inspect`, `find`, `audit` | explore a database, locate game files via an adapter, and check every `lang_*.db` in a game folder against the adapter's schema |
| `import` | import source text (safe to repeat; changed source text after a game update is counted) |
| `import-translated` | import an existing translation from `.pak`, `.db`, or `.json` |
| `search`, `show`, `stats` | search entries, inspect one, show progress |
| `edit`, `approve`, `history`, `revert` | edit with status (`mt`, `edited`, `approved`) and full version history |
| `translate` | machine-translate empty entries; saved per batch, stops cleanly on rate limits (exit code 3, safe to resume) |
| `qa` | quality checks; exits with code 1 on errors, so it works in CI |
| `export-db`, `export-pak`, `unpack-pak` | write a patched copy of the database or a pak, and unpack a pak |
| `export-csv`, `import-csv`, `export-json` | exchange with other translators |
| `serve` | local web editor |
| `user-add`, `user-list`, `user-remove` | editor accounts (personal tokens) so changes are attributed |

Export refuses to run while any entry has tags or variables that do not match the source text (override with `--skip-check`), and `--only-approved` writes approved entries only.

## Quality checks

| Code | Severity | Meaning |
|---|---|---|
| `placeholder` | error | a tag or variable is missing or extra compared with the source |
| `urutan_tag` | error | opening and closing tags are not nested correctly |
| `sisa_penanda` | error | a temporary machine-translation marker was left in the result |
| `glosarium` | warning | a glossary term was not translated as listed |
| `tidak_konsisten` | warning | the same source text was translated different ways |
| `sama_dengan_sumber` | warning | translation is identical to the source |
| `panjang` | warning | translation is much longer than the source |

Tags are protected during machine translation by replacing them with unique markers (`⟦0⟧`) and restoring them afterwards. A result in which any marker is missing, duplicated, or foreign is rejected and never saved.

## Machine translation

| Provider | Cost | Notes |
|---|---|---|
| `libre` (default) | free | your own LibreTranslate server; `--url` or env `LIBRETRANSLATE_URL` |
| `mymemory` | free, daily limit | `--email` or env `MYMEMORY_EMAIL` raises the limit; text is split into 450-character chunks |
| `claude` | paid, per usage | needs an API key (env `ANTHROPIC_API_KEY`); sends your glossary as required terms; `--max-chars` caps the total characters sent; pricing and rate limits are in the official docs at docs.claude.com |

`--limit` defaults to 50 per run (`--limit 0` for everything), and `--dry-run` shows results without saving.

## Web editor

`gamelokal serve` opens an editor at `http://localhost:8000`:

- a searchable, filterable list (status, ID prefix) and a stacked progress bar;
- tags in the source are highlighted and can be inserted with one click, with tag warnings shown the moment you save;
- a **QA report** tab for the whole dataset, filterable by problem type;
- a **machine suggestion** button (enable with `--provider libre|mymemory|claude`): the suggestion is shown separately and only saved if you accept it; `--mt-budget` caps characters sent per server session (default 200,000 for Claude);
- **edit-conflict detection**: if someone else changed the same entry since you opened it, you choose between their version and overwriting it;
- version history with editor names and a revert button.

Working as a team: create one account per person with `gamelokal user-add NAME` (the token is shown once), then run `gamelokal serve --host 0.0.0.0`. Everyone opens their personal link (`?token=...`) and their changes are recorded under their name. Without accounts, any non-localhost address requires a shared `--token`. Traffic is not encrypted: use it on a trusted network or behind an HTTPS reverse proxy. It is not designed for the open internet.

Security notes: only localhost is served by default and foreign `Host` headers are rejected (DNS rebinding); tokens are stored hashed and compared in constant time; requests that change data must carry a custom header; SQL values are always parameterized. Details in [docs/ARSITEKTUR.md](docs/ARSITEKTUR.md) (Indonesian).

## Project layout

```
src/gamelokal/
  core/        read-only game DB access, workbench (SQLite), CSV, glossary, text utilities
  adapters/    per-game knowledge (Wuthering Waves: schema and location inside the pak)
  translate/   machine translation providers and tag protection
  qa/          quality checks
  pack/        patched database copy, and .pak writer/reader
  web/         local HTTP server and single-file web UI
  cli.py       command line
tests/         70 automated tests
legacy/        the original single-file script this project grew from
docs/          architecture and roadmap (Indonesian)
```

Design principles: the game database is never modified (opened read-only, output goes to a copy); the workbench is the single source of truth; no runtime dependencies; every operation is safe to repeat and resume; export is gated on tag correctness.

## Limitations

- The `.pak` writer emits a single-file, version-12, uncompressed and unencrypted pak. It follows the format the original script was verified against, but **output from this repository has not yet been loaded by the game**.
- Only `lang_multi_text.db` has been checked against the Wuthering Waves adapter. Run `gamelokal audit` on a full game folder to check the others.
- The MyMemory and Claude providers are tested against local fake servers, not the live services.
- Two people editing at once is handled by conflict detection, not live sync: the list does not update until reloaded.
- No HTTPS, no password accounts; see the web editor section above.
- Only SQLite sources are supported so far.

## Legal

Do not commit original game files to this repository (`*.db` and `*.pak` are git-ignored). Read the game's terms of service before distributing a mod. This project is not affiliated with any game publisher.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (Indonesian). Run `pip install -e ".[dev]" && pytest`. License: MIT.
