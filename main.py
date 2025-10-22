from fastapi import FastAPI, Form
import requests

app = FastAPI()

BITRISE_APP_URL = "https://app.bitrise.io/app/d626fae8-c6e6-4f66-8ff4-454033d00cbc/build/start.json"
BITRISE_TRIGGER_TOKEN = "xtvmbYAqLgWYCwNLrebbgg"

WORKFLOWS = {
    "uat": "uatRelease",
    "uat-no-test": "uatReleaseWithoutTest",
    "preprod": "preProdReleaseMonorepo",
    "uat-debug": "uatQADebug"
}

@app.post("/trigger-build")
def trigger_build(text: str = Form(...)):
    # Parse command
    try:
        branch, workflow_nickname = text.strip().split()
        workflow_id = WORKFLOWS[workflow_nickname]
    except Exception:
        return {"text": "❌ Invalid format. Use `/build-app <branch> <workflow>`"}

    # Trigger Bitrise build
    payload = {
        "build_params": {"branch": branch, "workflow_id": workflow_id},
        "hook_info": {"build_trigger_token": BITRISE_TRIGGER_TOKEN, "type": "bitrise"},
        "triggered_by": "slack"
    }
    resp = requests.post(BITRISE_APP_URL, json=payload)
    if resp.status_code != 201:
        return {"text": f"❌ Failed to trigger build: {resp.text}"}

    build_slug = resp.json()["build_slug"]
    build_url = f"https://app.bitrise.io/build/{build_slug}?tests_filter_status=all&tab=artifacts"

    # Return Slack message with embedded link
    return {
        "text": f"🚀 Build triggered for *{branch}* with workflow *{workflow_id}*\n< {build_url} | View Build & Artifacts >"
    }
