# Packaging Recipes & Reusable Profiles

When packaging an application for the first time—especially a managed-runtime project (`--type runtime`) or a complex GUI app—the Agent inspects the project's manifests, determines runtime dependencies, decides the environment preparation command (`prepare_cmd`) and launcher (`runtime_cmd`), and extracts icons.

The **Recipe System** (`<package-name>.recipe.json`) captures all of these discoveries into a reusable profile. When a new version of the software is released later, packaging can be re-executed deterministically in a single command **with zero LLM re-analysis**.

---

## 1. Structure of a Recipe File (`<package-name>.recipe.json`)

```json
{
  "recipe_version": "1.2",
  "name": "weather-cli",
  "type": "runtime",
  "arch": "amd64",
  "section": "devel",
  "maintainer": "Maintainer <admin@example.com>",
  "homepage": "https://example.com",
  "description": "Weather CLI utility",
  "is_gui": false,
  "desktop_name": null,
  "category": "Utility;",
  "depends": [
    "python3"
  ],
  "prepare_cmd": "python3 -m venv --copies venv && ./venv/bin/pip install --no-cache-dir -r requirements.txt",
  "runtime_cmd": "/opt/weather-cli/venv/bin/python3",
  "entrypoint": "main.py",
  "env_vars": [
    "PYTHONPATH=/opt/weather-cli"
  ],
  "apparmor": false,
  "systemd_service": null,
  "icon_path": null,
  "last_built_version": "1.2.0"
}
```

### Key Runtime Reuse Fields
- `prepare_cmd`: Automatically re-runs environment initialization (e.g., `venv` creation + `pip install`, or `npm install --omit=dev`) inside `/opt/<name>/` for the new version's source tree.
- `runtime_cmd` & `entrypoint`: Rebuilds the exact `/usr/bin/<name>` wrapper without needing to re-parse `pyproject.toml`, `package.json`, or `MANIFEST.MF`.
- `env_vars`: Preserves custom environment variables exported in the launcher script.
- `icon_path`: Points to the persistent `<package-name>.icon.<ext>` file saved alongside the recipe during the first build.

---

## 2. Generating and Reusing Recipes

By default, `make_deb.py` writes `<package-name>.recipe.json` into `--output-dir` (or to the path given by `--save-recipe`).

```bash
# First build: Agent determines runtime hooks and saves recipe
python3 scripts/make_deb.py \
  --source ./weather_cli_v1.2.0 \
  --name weather-cli \
  --type runtime \
  --prepare-cmd "python3 -m venv --copies venv && ./venv/bin/pip install --no-cache-dir -r requirements.txt" \
  --runtime-cmd "/opt/weather-cli/venv/bin/python3" \
  --entrypoint "main.py" \
  --save-recipe ./weather-cli.recipe.json

# Future upgrade: Reuse recipe directly on new source directory or binary
python3 scripts/make_deb.py \
  --source ./weather_cli_v1.3.0 \
  --recipe ./weather-cli.recipe.json
```

### Standalone Per-Package Builder Script (`--generate-builder`)

Pass `--generate-builder ./build_<name>_deb.py` to embed the entire recipe into a standalone executable script:
```bash
./build_weather-cli_deb.py ./weather_cli_v1.3.0
```
