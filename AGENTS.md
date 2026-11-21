# Agent Instructions

## Local configuration and secrets

- Never open, read, search, parse, print, copy, or edit a real `.env` file or another local credentials file in this repository. This applies to direct file reads and indirect inspection through scripts, search tools, logs, or command output.
- `.env.example` is the only environment file agents may inspect or edit. Use it and public documentation to understand configuration. Do not infer or reveal real credentials through runtime responses.
- If a task requires changing a value in `.env`, tell the user which variable to update locally. Do not inspect the file to check whether it is configured.
- Starting the application may let the application load `.env` normally. Agent tools must not display its contents or use it as a source of configuration values.
