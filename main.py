from fastapi import FastAPI, Form, Request, BackgroundTasks
import requests
import asyncio
import os

app = FastAPI()

# -------------------------------
# Configuration
# -------------------------------
BITRISE_APP_URL = os.getenv(
    "BITRISE_APP_URL",
    "https://app.bitrise.io/app/d626fae8-c6e6-4f66-8ff4-454033d00cbc/build/start.json"
)
BITRISE_TRIGGER_TOKEN = os.getenv("BITRISE_TRIGGER_TOKEN", "xtvmbYAqLgWYCwNLrebbgg")
BITRISE_API_TOKEN = os.getenv("BITRISE_API_TOKEN", "bitpat_nFBAqmwH5YxTFELZ8O7pkS3v4VQKTl_D0-3eq_hctoOOhARnnN8SnWcCLSL2QTvD4Fmux_l_YYcHsq2Rzb9umw_q1DQa")
SELF_URL = os.getenv("SELF_URL", "https://bitrise-bot.onrender.com")

WORKFLOWS = {
    "uat": "uatRelease",
    "uat-no-test": "uatReleaseWithoutTest",
    "preprod": "preProdReleaseMonorepo",
    "uat-debug": "uatQADebug"
}

# Store response URLs temporarily for webhook updates
build_tracking = {}

# -------------------------------
# Slack Command Endpoint
# -------------------------------
@app.post("/trigger-build")
async def trigger_build(background_tasks: BackgroundTasks, text: str = Form(...), response_url: str = Form(None)):
    """
    Slash command: /build-im-retail-app <branch> <workflow>
    Immediately acknowledges to Slack and triggers Bitrise build asynchronously.
    """
    try:
        branch, workflow_nickname = text.strip().split()
        workflow_id = WORKFLOWS.get(workflow_nickname)
        if not workflow_id:
            return {"text": "❌ Unknown workflow. Try one of: `uat`, `uat-no-test`, `preprod`, `uat-debug`"}
    except Exception:
        return {"text": "❌ Invalid format. Use `/build-im-retail-app <branch> <workflow>`"}

    # Respond immediately to Slack (avoid timeout)
    ack_message = {
        "response_type": "in_channel",
        "text": f"🚀 Build request received for *{branch}* → workflow *{workflow_id}*\n⏳ Hang tight..."
    }

    # Trigger Bitrise build asynchronously
    background_tasks.add_task(start_bitrise_build, branch, workflow_id, response_url)

    return ack_message


def start_bitrise_build(branch: str, workflow_id: str, response_url: str):
    """Triggers a Bitrise build and informs Slack about build start."""
    payload = {
        "build_params": {"branch": branch, "workflow_id": workflow_id},
        "hook_info": {"build_trigger_token": BITRISE_TRIGGER_TOKEN, "type": "bitrise"},
        "triggered_by": "slack"
    }

    try:
        resp = requests.post(BITRISE_APP_URL, json=payload, timeout=30)
        if resp.status_code != 201:
            requests.post(response_url, json={"text": f"❌ Failed to trigger build: {resp.text}"})
            return

        build_slug = resp.json().get("build_slug")
        build_url = f"https://app.bitrise.io/build/{build_slug}?tab=artifacts"
        build_tracking[build_slug] = {"response_url": response_url}

        msg = {
            "response_type": "in_channel",
            "text": f":rocket: *Build started!* Branch: *{branch}* | Workflow: *{workflow_id}*\n"
                    f"<{build_url}|🔗 View Build & Artifacts>\n"
                    f"🕒 I’ll update you once it’s done!"
        }
        requests.post(response_url, json=msg)

    except Exception as e:
        requests.post(response_url, json={"text": f"⚠️ Build trigger failed: {e}"})


# -------------------------------
# Bitrise Webhook Endpoint
# -------------------------------
@app.post("/bitrise-webhook")
async def bitrise_webhook(request: Request):
    """Receives Bitrise build completion webhook and updates Slack."""
    payload = await request.json()
    print("Received webhook:", payload)

    build_slug = payload.get("build_slug")
    status_text = payload.get("status_text", "Finished")
    build_url = payload.get("build_url", f"https://app.bitrise.io/build/{build_slug}")

    # Retrieve Slack callback
    info = build_tracking.pop(build_slug, None)
    if not info or "response_url" not in info:
        print("⚠️ No response_url found for this build")
        return {"status": "ok"}

    response_url = info["response_url"]

    # Try fetching artifacts (APK)
    apk_url = None
    try:
        api_url = f"https://api.bitrise.io/v0.1/apps/d626fae8-c6e6-4f66-8ff4-454033d00cbc/builds/{build_slug}/artifacts"
        headers = {"Authorization": f"token {BITRISE_API_TOKEN}"}
        art_resp = requests.get(api_url, headers=headers, timeout=30)

        if art_resp.ok:
            artifacts = art_resp.json().get("data", [])
            for a in artifacts:
                if a.get("title", "").endswith(".apk"):
                    artifact_slug = a["slug"]
                    url_resp = requests.get(f"{api_url}/{artifact_slug}", headers=headers, timeout=30)
                    if url_resp.ok:
                        apk_url = url_resp.json()["data"]["expiring_download_url"]
                        break
    except Exception as e:
        print("Artifact fetch error:", e)

    # Compose Slack message
    emoji = "✅" if "success" in status_text.lower() else "❌"
    msg = {
        "response_type": "in_channel",
        "text": (
            f"{emoji} *Build {status_text}!* \n"
            f"<{build_url}|🧱 View Build>\n"
            f"{'📦 <' + apk_url + '|Download APK>' if apk_url else ''}"
        )
    }

    requests.post(response_url, json=msg)
    return {"status": "ok"}


# -------------------------------
# Health Check & Self-Ping (Keep-Alive)
# -------------------------------
@app.get("/")
def health():
    return {"status": "ok"}


async def keep_alive():
    """Prevents Render from idling by pinging itself every 4 minutes."""
    while True:
        try:
            requests.get(f"{SELF_URL}/", timeout=10)
        except Exception as e:
            print("Keep-alive ping failed:", e)
        await asyncio.sleep(20)  # 20 seconds


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(keep_alive())
