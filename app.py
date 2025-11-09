from google import genai
from google.genai import types
from google.genai.types import Content, Part
from playwright.sync_api import sync_playwright
from typing import Any, Dict, List, Tuple
import time
import termcolor
from pathlib import Path

# Initialize client (reads key from env or local file)

def load_api_key() -> str:
    """Load Gemini API key from a local file named 'gemini_api_key' next to this script.

    The file must contain the key on a single line. No environment variable fallback.
    """
    key_file = Path(__file__).with_name("gemini_api_key")
    if key_file.exists():
        content = key_file.read_text(encoding="utf-8").strip()
        if content:
            return content
    raise RuntimeError("Missing API key file. Create a 'gemini_api_key' file next to app.py with your key.")


API_KEY = load_api_key()
client = genai.Client(api_key=API_KEY)

# === CONFIG ===
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900
MAX_APPLICATIONS = 3  # how many jobs to apply per session
JOB_PORTAL = "https://www.linkedin.com/jobs"
USER_GOAL = f"Go to {JOB_PORTAL}, search for 'Software Engineer Intern Remote India', and apply to {MAX_APPLICATIONS} jobs automatically. Use uploaded resume if prompted."

# =============== Helper Functions ===============

def denormalize_x(x: int, screen_width: int) -> int:
    return int(x / 1000 * screen_width)

def denormalize_y(y: int, screen_height: int) -> int:
    return int(y / 1000 * screen_height)

def get_safety_confirmation(safety_decision):
    termcolor.cprint("⚠️  Safety system requires confirmation!", color="yellow")
    print(safety_decision["explanation"])
    decision = input("Proceed with this action? [Y/N]: ").strip().lower()
    if decision.startswith("y"):
        return "CONTINUE"
    return "TERMINATE"

def execute_function_calls(candidate, page, screen_width, screen_height):
    results = []
    for part in candidate.content.parts:
        if not hasattr(part, "function_call") or not part.function_call:
            continue

        fname = part.function_call.name
        args = part.function_call.args
        print(f"🖱️  Executing: {fname} {args}")
        extra_fields = {}

        # Handle safety decisions
        if "safety_decision" in args:
            decision = get_safety_confirmation(args["safety_decision"])
            if decision == "TERMINATE":
                print("Agent terminated by user confirmation.")
                break
            extra_fields["safety_acknowledgement"] = True

        try:
            if fname == "open_web_browser":
                pass
            elif fname == "click_at":
                x, y = denormalize_x(args["x"], screen_width), denormalize_y(args["y"], screen_height)
                page.mouse.click(x, y)
            elif fname == "type_text_at":
                x, y = denormalize_x(args["x"], screen_width), denormalize_y(args["y"], screen_height)
                page.mouse.click(x, y)
                page.keyboard.press("Meta+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(args["text"])
                if args.get("press_enter", True):
                    page.keyboard.press("Enter")
            elif fname == "scroll_document":
                direction = args.get("direction", "down")
                amount = 1000 if direction == "down" else -1000
                page.mouse.wheel(0, amount)
            elif fname == "key_combination":
                page.keyboard.press(args["keys"])
            else:
                print(f"⚠️ Skipping unimplemented action: {fname}")
        except Exception as e:
            print(f"❌ Error executing {fname}: {e}")
            extra_fields["error"] = str(e)

        page.wait_for_load_state("load", timeout=8000)
        time.sleep(1)
        results.append((fname, extra_fields))
    return results

def get_function_responses(page, results):
    screenshot = page.screenshot(type="png")
    url = page.url
    function_responses = []
    for name, result in results:
        function_responses.append(
            types.FunctionResponse(
                name=name,
                response={"url": url, **result},
                parts=[types.FunctionResponsePart(
                    inline_data=types.FunctionResponseBlob(
                        mime_type="image/png",
                        data=screenshot
                    )
                )]
            )
        )
    return function_responses

# =============== Main Agent Loop ===============

print("🌐 Launching browser...")
playwright = sync_playwright().start()
browser = playwright.chromium.launch(headless=False)
context = browser.new_context(viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT})
page = context.new_page()
page.goto("https://www.google.com")

config = types.GenerateContentConfig(
    tools=[types.Tool(
        computer_use=types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER)
    )],
    thinking_config=types.ThinkingConfig(include_thoughts=True),
)

contents = [
    Content(role="user", parts=[
        Part(text=USER_GOAL),
        Part.from_bytes(data=page.screenshot(type="png"), mime_type="image/png")
    ])
]

print(f"🎯 Task: {USER_GOAL}")

try:
    for turn in range(10):
        print(f"\n---- Turn {turn+1} ----")
        response = client.models.generate_content(
            model="gemini-2.5-computer-use-preview-10-2025",
            contents=contents,
            config=config
        )

        candidate = response.candidates[0]
        contents.append(candidate.content)

        if not any(p.function_call for p in candidate.content.parts):
            text_output = " ".join([p.text for p in candidate.content.parts if hasattr(p, "text")])
            print("✅ Agent finished:", text_output)
            break

        results = execute_function_calls(candidate, page, SCREEN_WIDTH, SCREEN_HEIGHT)
        function_responses = get_function_responses(page, results)
        contents.append(Content(role="user", parts=[Part(function_response=fr) for fr in function_responses]))

finally:
    print("\n🧹 Cleaning up...")
    browser.close()
    playwright.stop()
