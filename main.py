from fastapi import FastAPI, Form
import requests

app = FastAPI()

BITRISE_APP_URL = "https://app.bitrise.io/app/d626fae8-c6e6-4f66-8ff4-454033d00cbc/build/start.json"
BITRISE_TRIGGER_TOKEN = "xtvmbYAqLgWYCwNLrebbgg"

# Mapping nicknames to workflow IDs
WORKFLOW_MAP = {
    "uat": "uatRelease",
    "uat-no-test": "uatReleaseWithoutTest",
    "preprod": "preProdRelease",
    "uat-debug": "uatQADebug",
}

@app.post("/trigger-build")
def trigger_build(text: str = Form(...)):
    parts = text.strip().split()

    if len(parts) < 2:
        return {
            "text": "⚠️ Usage: `/build-app <branch> <env>`\nExample: `/build-app master uat`"
        }

    branch_name, env_nickname = parts[0], parts[1].lower()
    workflow_id = WORKFLOW_MAP.get(env_nickname)

    if not workflow_id:
        valid_keys = ", ".join(WORKFLOW_MAP.keys())
        return {"text": f"❌ Invalid environment: *{env_nickname}*\nValid options: {valid_keys}"}

    payload = {
        "build_params": {
            "branch": branch_name,
            "workflow_id": workflow_id,
        },
        "hook_info": {
            "build_trigger_token": BITRISE_TRIGGER_TOKEN,
            "type": "bitrise",
        },
        "triggered_by": "Slack Bot",
    }

    response = requests.post(BITRISE_APP_URL, json=payload, headers={"Content-Type": "application/json"})

    if response.status_code == 201:
        return {"text": f"🚀 Build triggered for *{branch_name}* with workflow *{workflow_id}*"}
    else:
        return {
            "text": f"❌ Build trigger failed ({response.status_code}) — {response.text}"
        }

