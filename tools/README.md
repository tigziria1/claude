# Tools

Deterministic Python scripts the agent calls from workflows.

- One task per script, runnable from the CLI (`python tools/<name>.py --help`)
- Load secrets with `python-dotenv` from `.env`; never hardcode keys
- Write intermediate files to `.tmp/`
