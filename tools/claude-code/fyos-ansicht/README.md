# fyos-ansicht — built FYOS views in the terminal

A mod for Claude Code. When the agent builds a view with the Hub plugin `gui` (metrics, diagram, table, calculator …),
the mod opens it on the right in the terminal's panel without taking the focus away from you. Claude Code in the
terminal is not an MCP Apps host and therefore cannot show the app itself. So the Hub delivers the view as a whole page
(`GET /hub/gui/<id>`; live sources reload through `/hub/gui/<id>/daten`), and the mod terminal-browser draws it as a
picture into its panel.

## Requirements

- A running FYOS Hub with the plugin `gui` (it belongs to the core) and Claude Code using the Hub as an MCP server, for
  example `claude mcp add --transport http fyos http://localhost:8080/mcp`.
- Claude Code itself must be able to reach the Hub, not just the shell (section "Hub address").
- The mod terminal-browser (project [zenbu-labs/terminal-browser](https://github.com/zenbu-labs/terminal-browser)) with
  its app, and a terminal with the kitty graphics protocol, such as kitty or Ghostty. That project covers setup and the
  app's settings (including telemetry). Without it, fyos-ansicht does nothing.
- Mods use Claude Code's "function hooks" interface. It may change between versions. Where your version does not offer
  it by itself, set `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` under `env` in Claude Code's settings file; terminal-browser
  requires the same. This mod passes `claude plugin validate` and `claude plugin test` with Claude Code 2.1.295.

## Setting up

In a checkout of this repo, in Claude Code:

```text
/plugin marketplace add ./tools/claude-code
/plugin install fyos-ansicht@fyos-tools
```

Then restart Claude Code. For one session only and without installing:

```sh
claude --plugin-dir tools/claude-code/fyos-ansicht
```

## Using it

- When Claude calls `gui.bauen` or `gui.zeigen` with an `id`, also through `hub__call_tool`, the mod opens the view on
  the right in the panel. The focus stays in the input field; a click into the panel gives it the keyboard. The list of
  all views and plain data queries open nothing.
- `/ansicht` opens the last view shown in this session again, `/ansicht g-…` a particular one (the id is in the answer
  of `gui.bauen`), `/ansicht zu` closes the panel.
- `FYOS_ANSICHT_AUTO=0` turns off automatic opening. `/ansicht` still works.
- A live view (`gui.bauen` with `quelle`) reloads in the panel by itself.

## Hub address

`FYOS_HUB_URL` names the Hub; the default is `http://localhost:8080`, the Hub's standard port. It is the same address
FYOS gives the agent, with `/mcp` at the end (`http://localhost:8080/mcp`). The mod cuts off the `/mcp`, because the
page lives at `/hub/gui/<id>` on the Hub itself. Set the variable before you start Claude Code, or under `env` in
Claude Code's settings file.

Since 0.1.1 the shell also passes `/hub/gui/…` through, read-only (see `docs/HUB-CONTRACT.md`, section "The shell's
nginx"). So the mod only needs an address at which the shell or the Hub answers. Claude Code itself needs the Hub for
the MCP connection, because `/mcp` does not go through the shell. The simplest is therefore to point `FYOS_HUB_URL` at
the same address as the MCP connection:

- **`fyos-hub` started directly:** `http://localhost:8080`, the default.
- **Docker Compose:** the Hub publishes no port. An override file next to `docker-compose.yml` opens one, only for this
  machine, because the Hub is open inside: `FYOS_HUB_URL=http://127.0.0.1:8081/mcp`.

  ```yaml
  # deploy/compose/docker-compose.override.yml
  services:
    hub:
      ports:
        - "127.0.0.1:8081:8080"
  ```

  Without `FYOS_HUB_URL` the default hits the shell at `http://localhost:8080` (or the port from `FYOS_PORT`); the
  views open there too.
- **Kubernetes:** `kubectl port-forward svc/hub 8081:8080` (with `-n <namespace>`), then
  `FYOS_HUB_URL=http://127.0.0.1:8081/mcp`. The shell's address works too, if terminal-browser has its login.

## What the mod does

- It reads only the results of `gui__bauen`, `gui__zeigen` and `hub__call_tool` and passes them on unchanged. It sends
  nothing to the model, reads no files, starts no processes and has no network of its own. terminal-browser does the
  loading.
- It reads the environment variables `FYOS_HUB_URL`, `FYOS_ANSICHT_AUTO` and `CLAUDE_JOB_DIR` and writes none.
- As in the shell, the view runs in a sandbox without network: the script the agent generated reaches neither the Hub
  nor the internet.

## Limits

- Only in Claude Code's terminal interface. The desktop app, claude.ai and the phone are MCP Apps hosts and show the
  app themselves.
- In attached background sessions (the mod recognises them by `CLAUDE_JOB_DIR`) kitty draws the panel, but not the
  picture in it: it stays grey. The mod opens nothing there and shows a hint. In a normal session `/ansicht <id>` opens
  the view.
- If the Hub cannot be reached, the panel shows only the browser's error page. The mod does not check this beforehand.
- Without the mod, `tools/gui_datei.py` turns a view into an HTML file that `--oeffnen` shows in the default browser.

## Tests

```sh
claude plugin validate tools/claude-code/fyos-ansicht     # static check of the hooks and calls
claude plugin test tools/claude-code/fyos-ansicht         # 6 tests, without a session and without network
```

`claude plugin test` is Claude Code's runner: the tests take their tools from the test kit that Claude Code itself
ships (module "claude-code/testing"). They do not run with another runner, and the CI of this repo therefore does not
run them.
