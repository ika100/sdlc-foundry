# platform plugin

The `platform` noun: the platform itself, as installed in your repos.

| Command | Does |
|---|---|
| `/platform:doctor` | Preflight check of tools, scopes, plugins and the repo's platform version (`cplat platform doctor`); also the rows `operator keda`, `operator metrics-server` and `resource metrics` for scaled instances |
| `/platform:update` | Pull the current platform skeleton into this repo; `--migrate` converts a 4.x repo to 5.0 (`cplat platform update`) |
| `/platform:fleet` | Bring every repo built from the platform up to the current release (`cplat platform fleet update`) |
| `/platform:runs` | Run records, agent metrics, usage and cost (`cplat platform runs report`) |
| `/platform:ui` | Start the local console: Inbox, Board and System in the browser (`cplat platform ui`; see [docs/console.md](../../docs/console.md)) |
| `/platform:retro` | The weekly platform retro (`cplat platform retro`) |

Needs the `shared` plugin (it puts `cplat` on the Bash PATH).
