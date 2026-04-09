# Dialogue Visual Editor

Desktop tool for reviewing and editing visual novel dialogue and translation data.

It is focused on translator workflows around structured dialogue files, with UI support for:

- block-by-block dialogue editing
- speaker mapping and color management
- translation-state persistence
- audit/search tools for consistency, sanitize passes, control-code mismatches, and term usage
- mass-translate prompt preparation and apply flows

## Supported Project Types

- RPG Maker MV / MZ projects and their JSON data files
- TyranoScript projects, including `.ks`, `plugins.js`, and `config.tjs`
- No usable Wolf RPG support at the moment

Wolf RPG support is not currently implemented to a usable level. It should be possible to extend the app in that direction later, but today it does not provide a practical Wolf RPG workflow. Any future support would likely still require an unencrypted game or another tool to extract and patch data.

## Requirements

- Python 3.13
- Windows is the primary target environment

## Setup

```powershell
python -m pip install -r requirements.txt
python -m pip install pytest pyright
```

## Run

```powershell
python .\dialogue_visual_editor.pyw
```

If you want the console attached instead of the `.pyw` launcher:

```powershell
python .\app.py
```

## Verification

Run the same checks used for local validation and CI:

```powershell
pytest -q
pyright
```
