import asyncio
import base64
import os
import traceback
from contextlib import asynccontextmanager

import anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager


load_dotenv()

HEADLESS = os.getenv("EDGE_HEADLESS", "false").lower() == "true"
RECYCLE_AFTER = int(os.getenv("EDGE_RECYCLE_AFTER", "200"))
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "claude-sonnet-4-6")
# Cap HTML→text extraction at ~200K chars before sending to the model.
# Sonnet 4.6 has a 1M context window, but we run async and want to bound cost.
MAX_EXTRACT_CHARS = int(os.getenv("EDGE_MAX_EXTRACT_CHARS", "200000"))

llm = anthropic.AsyncAnthropic()


class FetchRequest(BaseModel):
    url: str
    wait_time: int = 3
    timeout: int = 30
    return_screenshot: bool = False
    summarize: bool = True
    instructions: str | None = None


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
    return "\n".join(lines)


async def _summarize(url: str, title: str, text: str, instructions: str | None) -> str:
    extra = f"\n\nUser instructions: {instructions}" if instructions else ""
    prompt = (
        f"The following is text extracted from {url} (title: {title!r}). "
        "Organize and summarize the meaningful content: main topic, key points, "
        "important facts/figures, and any actionable info. Drop boilerplate "
        "(nav, ads, cookie banners, footers). Use clear markdown headings."
        f"{extra}\n\n---\n{text[:MAX_EXTRACT_CHARS]}"
    )
    msg = await llm.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return next((b.text for b in msg.content if b.type == "text"), "")


def create_driver(headless: bool):
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
    )

    options.add_experimental_option(
        "excludeSwitches", ["enable-automation"]
    )
    options.add_experimental_option(
        "useAutomationExtension", False
    )

    # Dedicated automation profile. Do NOT open this directory in a manual
    # Edge window — Chromium enforces a singleton lock per user-data-dir.
    options.add_argument(
        r"--user-data-dir=E:\Projects\Edge\User Data"
    )
    options.add_argument("--profile-directory=Profile 1")

    driver = webdriver.Edge(
        service=Service(EdgeChromiumDriverManager().install()),
        options=options,
    )

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', "
        "{ get: () => undefined })"
    )

    return driver


# Single persistent driver shared across requests. Selenium drivers are
# not thread-safe, so all access is serialized through driver_lock.
state: dict = {"driver": None, "anchor": None, "uses": 0}
driver_lock = asyncio.Lock()


def _boot_driver():
    driver = create_driver(HEADLESS)
    driver.get("about:blank")
    state["driver"] = driver
    state["anchor"] = driver.current_window_handle
    state["uses"] = 0


def _shutdown_driver():
    d = state.get("driver")
    if d is not None:
        try:
            d.quit()
        except Exception:
            pass
    state["driver"] = None
    state["anchor"] = None


def _ensure_healthy():
    # If the browser died (crash, user closed it manually) we'd see an
    # exception on any property access. Rebuild from scratch in that case.
    d = state.get("driver")
    if d is None:
        _boot_driver()
        return
    try:
        _ = d.current_url
    except Exception:
        _shutdown_driver()
        _boot_driver()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _boot_driver()
    try:
        yield
    finally:
        _shutdown_driver()


app = FastAPI(lifespan=lifespan)


@app.post("/fetch")
async def fetch_page(req: FetchRequest):
    try:
        async with driver_lock:
            _ensure_healthy()
            d = state["driver"]

            d.switch_to.new_window("tab")
            try:
                d.set_page_load_timeout(req.timeout)
                d.get(req.url)

                # asyncio.sleep so the lock-holding coroutine doesn't block
                # the event loop while waiting for JS.
                await asyncio.sleep(req.wait_time)

                title = d.title
                html = d.page_source
                screenshot_b64 = None
                if req.return_screenshot:
                    screenshot_b64 = base64.b64encode(
                        d.get_screenshot_as_png()
                    ).decode()
            finally:
                try:
                    d.close()
                finally:
                    d.switch_to.window(state["anchor"])

            state["uses"] += 1
            if state["uses"] >= RECYCLE_AFTER:
                _shutdown_driver()
                _boot_driver()

        # Lock released — LLM call doesn't block other requests' browser turn.
        result: dict = {"url": req.url, "title": title}
        if screenshot_b64 is not None:
            result["screenshot_base64"] = screenshot_b64

        text = _html_to_text(html)
        result["extracted_chars"] = len(text)

        if req.summarize and text:
            result["summary"] = await _summarize(
                req.url, title, text, req.instructions
            )
        else:
            result["text"] = text

        return result

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root():
    return {"message": "selenium edge backend running"}
