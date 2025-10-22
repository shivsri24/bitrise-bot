from fastapi import FastAPI, Form, Request
import requests
import threading
import time

app = FastAPI()

BITRISE_APP_URL = "https://app.bitrise.io/app/d626fae8-c6e6-4f66-8ff4-454033d00cbc/build/start.json"
BITRISE_TRIGGER_TOKEN = "xtvmbYAqLgWYCwNLrebbgg"

# Maps workflow nicknames to real workflow IDs
WORKFLOWS = {
    "uat": "uatRelease",
    "uat-no-test": "uatReleaseWithoutTest",
    "preprod": "preProdReleaseMonorepo",
    "uat-debug": "uatQADebug"
}

# In-memory store (in production use Redis or DynamoDB)
build_tracking = {}


@app.post("/trigger-build")
def trigger_build(text: str = Form(...), response_url: str = Form(default=None)):
    """
    Slack command: /build-im-retail-app <branch> <workflow>
    Slack automatically sends 'response_url' for delayed responses.
    """
    try:
        branch, workflow_nickname = text.strip().split()
        workflow_id = WORKFLOWS[workflow_nickname]
    except Exception:
        return {"text": "❌ Invalid format. Use `/build-im-retail-app <branch> <workflow>`"}

    # Trigger Bitrise build
    payload = {
        "build_params": {"branch": branch, "workflow_id": workflow_id},
        "hook_info": {"build_trigger_token": BITRISE_TRIGGER_TOKEN, "type": "bitrise"},
        "triggered_by": "slack"
    }
    resp = requests.post(BITRISE_APP_URL, json=payload)
    if resp.status_code != 201:
        return {"text": f"❌ Failed to trigger build: {resp.text}"}

    data = resp.json()
    build_slug = data["build_slug"]
    build_url = f"https://app.bitrise.io/build/{build_slug}?tab=artifacts"

    # Store Slack callback for later
    if response_url:
        build_tracking[build_slug] = {"response_url": response_url}

    # Immediate Slack message
    return {
        "response_type": "in_channel",
        "text": f"🚀 Build started for *{branch}* with workflow *{workflow_id}*\n< {build_url} | View Build >\nI'll update you when it finishes!"
    }


@app.post("/bitrise-webhook")
async def bitrise_webhook(request: Request):
    """
    Endpoint for Bitrise to call once build finishes.
    Configure this in Bitrise under:
    App > Code > Webhooks > Add webhook > Custom > https://<your-app>.onrender.com/bitrise-webhook
    """
    payload = await request.json()
    build_slug = payload.get("build_slug")
    status_text = payload.get("status_text", "")
    build_url = payload.get("build_url", "")

    # Fetch artifacts from Bitrise API
    artifacts_resp = requests.get(f"https://api.bitrise.io/v0.1/apps/d626fae8-c6e6-4f66-8ff4-454033d00cbc/builds/{build_slug}/artifacts",
                                  headers={"Authorization": f"token {BITRISE_TRIGGER_TOKEN}"})
    artifact_data = artifacts_resp.json().get("data", [])

    download_url = None
    for artifact in artifact_data:
        if artifact.get("artifact_type") == "android-apk":
            artifact_slug = artifact["slug"]
            # Get expiring download URL
            art_resp = requests.get(
                f"https://api.bitrise.io/v0.1/apps/d626fae8-c6e6-4f66-8ff4-454033d00cbc/builds/{build_slug}/artifacts/{artifact_slug}",
                headers={"Authorization": f"token {BITRISE_TRIGGER_TOKEN}"})
            download_url = art_resp.json()["data"]["expiring_download_url"]
            break

    # Post update to Slack
    if build_slug in build_tracking:
        response_url = build_tracking.pop(build_slug)["response_url"]
        message = {
            "response_type": "in_channel",
            "text": (
                f"✅ *Build Finished!* ({status_text})\n"
                f"<{build_url}|View Build>\n"
            )
        }
        if download_url:
            message["text"] += f"📦 <{download_url}|Download APK>"
        requests.post(response_url, json=message)

    return {"status": "ok"}
