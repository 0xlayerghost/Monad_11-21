# Project Instructions

## Local configuration and secrets

- Do not open, read, search, parse, print, copy, or edit any real `.env` file or other local credentials file. Do not inspect it indirectly with scripts, search tools, logs, or command output.
- Only `.env.example` may be inspected or edited as an environment file. Use it and public documentation for configuration guidance. Do not infer or disclose real credentials from runtime responses.
- When a real `.env` value must change, name the variable and ask the user to update it locally. The application itself may still load `.env` during normal startup; agent tools must not expose its contents.
