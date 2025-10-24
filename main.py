from fastapi import FastAPI, Form, Request, BackgroundTasks
import requests
import asyncio
import os

app = FastAPI()

BITRISE_APP_URL = os.getenv("BITRISE_APP_URL", "https://app.bitrise.io/app/d626fae8-c6e6-4f66-8ff4-454033d00cbc/build/start.json")
BITRISE_TRIGGER_TOKEN = os.getenv("BITRISE_TRIGGER_TOKEN", "xtvmbYAqLgWYCwNLrebbgg")
BITRISE_API_TOKEN = os.getenv("BITRISE_API_TOKEN", "bitpat_nFBAqmwH5YxTFELZ8O7pkS3v4VQKTl_D0-3eq_hctoOOhARnnN8SnWcCLSL2QTvD4Fmux_l_YYcHsq2Rzb9umw_q1DQa")  # For fetching artifacts

SELF_URL = os.getenv("SELF_URL", "https://bitrise-bot.onrender.com")

WORKFLOWS = {
    "uat": "uatRelease",
    "uat-no-test": "uatReleaseWithoutTest",
    "preprod": "preProdReleaseMonorepo",
    "uat-debug": "uatQADebug"
}

# Temporary storage of response URLs
build_tracking = {}

# -------------------------------
# Slack Command Endpoint
# -------------------------------
@app.post("/trigger-build")
def trigger_build(background_tasks: BackgroundTasks, text: str = Form(...), response_url: str = Form(None)):
    try:
        branch, workflow_nickname = text.strip().split()
        workflow_id = WORKFLOWS[workflow_nickname]
    except Exception:
        return {"text": "❌ Invalid format. Use `/build-im-retail-app <branch> <workflow>`"}

    payload = {
        "build_params": {"branch": branch, "workflow_id": workflow_id},
        "hook_info": {"build_trigger_token": BITRISE_TRIGGER_TOKEN, "type": "bitrise"},
        "triggered_by": "slack"
    }
    resp = requests.post(BITRISE_APP_URL, json=payload)

    if resp.status_code != 201:
        return {"text": f"❌ Failed to trigger build: {resp.text}"}

    build_slug = resp.json().get("build_slug")
    build_url = f"https://app.bitrise.io/build/{build_slug}?tab=artifacts"

    # Store Slack callback for webhook updates
    build_tracking[build_slug] = {"response_url": response_url}

    # Respond immediately
    return {
        "response_type": "in_channel",
        "text": f"🚀 Build started for *{branch}* using *{workflow_id}*\n"
                f"<{build_url}|🔗 View Build & Artifacts>\n"
                f"⏳ I’ll update you when it finishes!"
    }


# -------------------------------
# Bitrise Webhook Endpoint
# -------------------------------
@app.post("/bitrise-webhook")
async def bitrise_webhook(request: Request):
    payload = await request.json()
    print("Received webhook:", payload)

    build_slug = payload.get("build_slug")
    status_text = payload.get("status_text", "Finished")
    build_url = payload.get("build_url", f"https://app.bitrise.io/build/{build_slug}")

    # Fetch stored Slack response URL
    info = build_tracking.pop(build_slug, None)
    if not info or "response_url" not in info:
        print("⚠️ No response_url found for this build")
        return {"status": "ok"}

    response_url = info["response_url"]

    # Try to fetch artifacts (APK URL)
    apk_url = None
    try:
        api_url = f"https://api.bitrise.io/v0.1/apps/d626fae8-c6e6-4f66-8ff4-454033d00cbc/builds/{build_slug}/artifacts"
        headers = {"Authorization": f"token {BITRISE_API_TOKEN}"}
        art_resp = requests.get(api_url, headers=headers)
        if art_resp.ok:
            artifacts = art_resp.json().get("data", [])
            for a in artifacts:
                if a.get("title", "").endswith(".apk"):
                    artifact_slug = a["slug"]
                    url_resp = requests.get(f"{api_url}/{artifact_slug}", headers=headers)
                    if url_resp.ok:
                        apk_url = url_resp.json()["data"]["expiring_download_url"]
                        break
    except Exception as e:
        print("Artifact fetch error:", e)

    # Compose Slack message
    msg = {
        "response_type": "in_channel",
        "text": f"✅ *Build Finished!* ({status_text})\n"
                f"<{build_url}|🧱 View Build>\n"
                f"{'📦 <' + apk_url + '|Download APK>' if apk_url else ''}"
    }

    requests.post(response_url, json=msg)
    return {"status": "ok"}


# -------------------------------
# Health check & self-ping poller
# -------------------------------
@app.get("/")
def health():
    return {"status": "ok"}

async def keep_alive():
    while True:
        try:
            requests.get(f"{SELF_URL}/")
        except Exception as e:
            print("Keep-alive ping failed:", e)
        await asyncio.sleep(10)  # ping every 4 minutes (Render auto-sleep ~15 min)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(keep_alive())
