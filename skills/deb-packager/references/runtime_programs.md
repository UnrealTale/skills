# Managed Runtime Programs Packaging Guide (`--type runtime`)

All programs that depend on a language interpreter, virtual machine, or isolated dependency environment (Python, Java, Node.js, Ruby, .NET, PHP, Perl, Lua, etc.) share the exact same packaging mechanics under `--type runtime`.

---

## 1. The Unified Runtime Packaging Model

Instead of writing language-specific packaging scripts, the **Agent** inspects the project's manifest (`pyproject.toml`, `requirements.txt`, `package.json`, `META-INF/MANIFEST.MF`, `Gemfile`, `*.csproj`) once and supplies 4 universal parameters to `scripts/make_deb.py` (which are then saved into `<name>.recipe.json` for future upgrades):

1. **`--prepare-cmd` (Optional — Bundled/Isolated Environment Hook)**:
   - Executed inside the staged `/opt/<package-name>/` directory during build.
   - Used to create isolated environments (`python3 -m venv`, `npm install --omit=dev`, `bundle install`) so the target system doesn't suffer from host package conflicts or PEP 668 restrictions.
   - `make_deb.py` automatically rewrites any hardcoded build-time staging paths inside `/opt/<package-name>/` (such as `venv/bin/*` shebangs or `pyvenv.cfg`) to `/opt/<package-name>` and strips `.pyc` files.
2. **`--runtime-cmd` (Interpreter / VM Prefix)**:
   - The command prefix placed in `/usr/bin/<package-name>` (`exec <runtime_cmd> /opt/<package-name>/<entrypoint> "$@"`).
   - Examples: `python3`, `/opt/<name>/venv/bin/python3`, `java -Xms128m -Xmx512m -jar`, `node`, `dotnet`, `ruby`.
3. **`--entrypoint` (Relative Entry File in `/opt/<package-name>/`)**:
   - Examples: `main.py`, `app.jar`, `dist/index.js`, `MyApp.dll`.
4. **`--depends` (Debian Runtime Package Dependency)**:
   - Examples: `python3`, `default-jre | openjdk-21-jre | openjdk-17-jre`, `nodejs`, `ruby`, `dotnet-runtime-8.0`.

> **Automatic Architecture Detection (`all` vs `amd64`/`arm64`)**:
> When `--arch auto` (default) is used with `--type runtime`, `make_deb.py` scans `/opt/<package-name>/` after `--prepare-cmd` completes:
> - If any native ELF binary or `.so`/`.node` shared library exists inside `/opt/<package-name>/` (e.g. a bundled Python `venv` or Node native addon), it sets `Architecture` to the detected ELF architecture (`amd64`, `arm64`, etc.).
> - If `/opt/<package-name>/` contains only portable bytecode/scripts (`.jar`, `.py`, `.js`), it sets `Architecture: all`.

---

## 2. Reference Patterns by Ecosystem

| Ecosystem | Mode | `--prepare-cmd` (run in `/opt/<name>`) | `--runtime-cmd` | `--depends` |
| :--- | :--- | :--- | :--- | :--- |
| **Python (Isolated venv, PEP 668 safe)** | Isolated | `python3 -m venv --copies venv && ./venv/bin/pip install --no-cache-dir -r requirements.txt` | `/opt/<name>/venv/bin/python3` | `python3` |
| **Python (System packages)** | Host | *(none)* | `python3` | `python3, python3-requests` |
| **Java (Executable JAR)** | Host | *(none)* | `java -Xms64m -Xmx512m -jar` | `default-jre \| openjdk-21-jre \| openjdk-17-jre` |
| **Node.js (Bundled `node_modules`)** | Isolated | `npm install --omit=dev --no-audit` | `node` | `nodejs` |
| **Node.js (Single script / prebundled)** | Host | *(none)* | `node` | `nodejs` |
| **Ruby** | Isolated / Host | `bundle install --path vendor/bundle` *(or none)* | `ruby` | `ruby` |
| **.NET (Framework-dependent DLL)** | Host | *(none)* | `dotnet` | `dotnet-runtime-8.0` |

---

## 3. Common Build Commands

```bash
# 1. Python project with isolated virtualenv (PEP 668 compliant)
python3 scripts/make_deb.py \
  --source ./weather_cli \
  --name weather-cli \
  --version 1.2.0 \
  --type runtime \
  --prepare-cmd "python3 -m venv --copies venv && ./venv/bin/pip install --no-cache-dir -r requirements.txt" \
  --runtime-cmd "/opt/weather-cli/venv/bin/python3" \
  --entrypoint "main.py" \
  --depends "python3"

# 2. Java executable JAR
python3 scripts/make_deb.py \
  --source ./demo-app.jar \
  --name demo-app \
  --version 2.0.0 \
  --type runtime \
  --runtime-cmd "java -Xms128m -Xmx512m -jar" \
  --depends "default-jre | openjdk-21-jre | openjdk-17-jre"

# 3. Node.js CLI/App with production node_modules
python3 scripts/make_deb.py \
  --source ./my-node-app \
  --name my-node-app \
  --version 1.0.0 \
  --type runtime \
  --prepare-cmd "npm install --omit=dev --no-audit" \
  --runtime-cmd "node" \
  --entrypoint "index.js" \
  --depends "nodejs"
```
