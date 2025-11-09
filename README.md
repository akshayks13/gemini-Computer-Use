# Gemini 2.5 Computer Use Demos

This repository showcases three small Python agents that use Google's Gemini *computer use* capability with Playwright to control a real Chromium browser via vision + action function calls.

## Contents

| File | Purpose |
|------|---------|
| `app.py` | Job portal autopilot (preset goal to search/apply). |
| `agent.py` | General free-form goal agent (you supply any browsing objective). |
| `job_form.py` | Local job application form filler + automatic `resume.pdf` upload. |
| `job_application.html` | Simple form used by `app1.py` (no backend, shows submitted data). |
| `requirements.txt` | Python dependencies (`google-genai`, `playwright`, `termcolor`). |
| `gemini_api_key` | Single-line file holding your Gemini API key (ignored by git). |

## Quick Start

```zsh
# 1. Create & activate a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright Chromium browser (one-time)
python3 -m playwright install chromium

# 4. Add your API key file (single line)
echo "YOUR_GEMINI_API_KEY" > gemini_api_key
```

## Running Each Demo

### 1. Free‑form browsing agent
```zsh
python3 agent.py "Find Wikipedia article about Niagara Falls and open History section"
```

### 2. Local form filling (with resume)
Optionally place a `resume.pdf` next to `job_form.py` (the script auto-attaches it when the model clicks the file input).
```zsh
python3 job_form.py "Open the local job application form and fill it with: Full Name Jane Applicant, Email jane.applicant@example.com, Phone +1 555 000 9999, Position Software Engineer, Consent Yes, Cover letter: Motivated and quick learner. Attach resume.pdf and submit."
```
After submission the page shows a green summary box; no data leaves your machine.

### 3. Job portal autopilot
```zsh
python3 app.py
```
Edit inside `app.py` if you want to change:
- `USER_GOAL` (overall objective)
- `MAX_APPLICATIONS` (limit attempts)
- Viewport constants

## How It Works (All Scripts)
1. Take a screenshot of the current browser state.
2. Send screenshot + user goal to Gemini `gemini-2.5-computer-use-preview-10-2025`.
3. Receive structured function calls (e.g. `click_at`, `type_text_at`, `navigate`).
4. Execute them with Playwright, wait briefly, capture a new screenshot.
5. Provide the function responses (with screenshot) back to the model and iterate until it returns only text or we hit a turn cap.

## File-Specific Notes
- **`job_form.py` resume upload**: Uses Playwright's `filechooser` event to attach `resume.pdf` automatically—no manual dialog interaction needed by the model.
- **Selection clearing**: Agents use `Meta+A` (macOS) before typing to clear fields; adapt to `Control+A` for Linux/Windows if needed.
- **Safety/HITL**: When a model step includes a `safety_decision` argument you'll be prompted to confirm.

## Troubleshooting
| Issue | Fix |
|-------|-----|
| Missing browser | `python3 -m playwright install chromium` |
| Key error / auth | Ensure `gemini_api_key` file exists and contains a single line key |
| Model returns no actions | Refine goal; make it specific and actionable |
| Inaccurate clicks | Keep window unobstructed, keep viewport 1440×900 |
| Resume not attached | Confirm `resume.pdf` filename & location next to `job_form.py` |

Enjoy exploring Gemini Computer Use! 