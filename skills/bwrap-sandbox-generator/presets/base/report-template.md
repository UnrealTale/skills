<!--
================================================================================
MANDATORY LOCALIZATION & FILE-WRITING RULE FOR THE AGENT:
1. You MUST translate and write ALL section headings, table headers, field
   labels, policy explanations, capability descriptions, audit findings, and CLI
   usage comments in the EXACT LANGUAGE used by the user in their request!
   - If the user asked in Chinese (简体/繁体中文), write the entire report in Chinese.
   - If the user asked in English, write the entire report in English.
   - If the user asked in another language, write the entire report in that language.
2. You MUST save the rendered Markdown report to disk at `expected_report_file`
   (by default `<output-script-stem>-briefing.md` in the same directory as the
   generated script). Do NOT only output the report in chat without writing the
   file to disk!
================================================================================
-->

# [Localized Title: Sandbox Security Briefing] — `{{APP_ID}}`

## 1. [Localized: Overview & Audit Verification Status]
| [Localized: Field] | [Localized: Value] |
| :--- | :--- |
| **[Localized: Application ID]** | `{{APP_ID}}` |
| **[Localized: Generated Wrapper Script]** | `{{OUTPUT_SCRIPT}}` |
| **[Localized: Security Briefing File]** | `{{EXPECTED_REPORT_FILE}}` |
| **[Localized: Default Target Command]** | `{{DEFAULT_TARGET}}` |
| **[Localized: Static Security & Portability Audit (`audit.py`)]** | **{{AUDIT_STATUS}}** ({{AUDIT_SUMMARY_LOCALIZED}}) |

---

## 2. [Localized: Layer 1 — Runtime Environment & User Policy Choices]
- **[Localized: Runtime Preset (`--runtime`)]**: `{{RUNTIME_ID}}` — {{RUNTIME_DESCRIPTION_LOCALIZED}}
- **[Localized: Sandbox `$HOME` Mapping Policy (`--home-mode`)]**: `{{HOME_MODE}}` — {{HOME_POLICY_LOCALIZED}}
- **[Localized: Current Working Directory (`$PWD`) Policy (`--cwd-mode`)]**: `{{CWD_MODE}}` — {{CWD_POLICY_LOCALIZED}}
- **[Localized: Application Directory (`APP_DIR`) Policy (`--app-dir-mode`)]**: `{{APP_DIR_MODE}}` — {{APP_DIR_POLICY_LOCALIZED}}
- **[Localized: `/etc` Exposure Policy (`--etc-mode`)]**: `{{ETC_MODE}}` — {{ETC_POLICY_LOCALIZED}}

---

## 3. [Localized: Layer 2 — Software Category & Capability Presets]
- **[Localized: Category Preset (`--category`)]**: `{{CATEGORY_ID}}` (Freedesktop Standard: `{{FREEDESKTOP_CATEGORIES}}`) — {{CATEGORY_DESCRIPTION_LOCALIZED}}
- **[Localized: Default Network Policy (`ALLOW_NET`)]**: {{NET_POLICY_LOCALIZED}}
- **[Localized: Enabled Cross-Vendor Portable Capability Modules]**:
{{CAPABILITY_LIST_LOCALIZED}}
- **[Localized: Capability Overrides (`--add-cap` / `--drop-cap`)]**: {{CAPABILITY_OVERRIDES_LOCALIZED}}

---

## 4. [Localized: Non-Preset / Probed Extra Paths & Permissions (User-Approved Risk Items)]
> **[Localized: Security Notice]**: [Localized: Any path or primitive listed below lies outside the standard category presets and was explicitly reviewed and approved by the user.]

| [Localized: Type] | [Localized: Target / Argument] | [Localized: Access / Effect (Localized)] | [Localized: Source (Localized)] |
| :--- | :--- | :--- | :--- |
{{EXTRA_ITEMS_TABLE_ROWS_LOCALIZED}}

---

## 5. [Localized: Security Audit Details & Runtime Usage Cheatsheet]
### [Localized: Audit Findings (`audit.py`)]
- **[Localized: Checks Passed]**: {{AUDIT_CHECKS_PASSED_LIST}}
{{AUDIT_WARNINGS_LOCALIZED}}

### [Localized: Quick Runtime Usage & Override Flags]
```bash
# [Localized: Run normally with configured default policies]
{{OUTPUT_SCRIPT}} [app_args...]

# [Localized: Specify custom application ID to switch isolated persistent $HOME]
{{OUTPUT_SCRIPT}} -i <custom-id> [app_args...]

# [Localized: Record strace log inside sandbox for fallback debugging]
{{OUTPUT_SCRIPT}} --trace /tmp/{{APP_ID}}_trace.log [app_args...]

# [Localized: View assembled bwrap command before execution]
{{OUTPUT_SCRIPT}} -v [app_args...]

# [Localized: Extra mounts can be directly edited in the script header (RW_BINDS / RO_BINDS) or passed via environment variables]
EXTRA_RW_BINDS="/host/path:/sandbox/path" {{OUTPUT_SCRIPT}} [app_args...]
```
