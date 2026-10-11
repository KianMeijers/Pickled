import time, httpx, anthropic
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
class S(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    runware_api_key: SecretStr
KEY = S().runware_api_key.get_secret_value()
BASE = "https://api.runware.ai"
for m in ["claude-sonnet-5-5", "claude-opus-5-5", "anthropic:claude@opus-5.5", "claude-haiku-5-5"]:
    t = time.time()
    try:
        c = anthropic.Anthropic(base_url=BASE, auth_token=KEY, max_retries=0, timeout=120)
        r = c.messages.create(model=m, max_tokens=10, messages=[{"role":"user","content":"hi"}])
        print(m, "ok", r.model, round(time.time()-t,1))
    except Exception as e:
        print(m, "ERR", type(e).__name__, str(e)[:200], round(time.time()-t,1))
# x-api-key only (LangChain default auth)
r = httpx.post(f"{BASE}/v1/messages", headers={"x-api-key": KEY, "anthropic-version":"2023-06-01"},
    json={"model":"claude-sonnet-5-5","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}, timeout=60)
print("x-api-key only:", r.status_code, r.text[:200].replace(KEY,"<KEY>"))
# raw SSE: look for cost fields in message_delta / headers
with httpx.stream("POST", f"{BASE}/v1/messages", headers={"Authorization": f"Bearer {KEY}", "anthropic-version":"2023-06-01"},
    json={"model":"claude-sonnet-5-5","max_tokens":20,"stream":True,"messages":[{"role":"user","content":"hi"}]}, timeout=60) as r:
    print("stream headers:", [k for k in r.headers])
    for line in r.iter_lines():
        if "message_delta" in line or "message_start" in line or "cost" in line.lower():
            print(line[:400])
# Runware native pricing check: does a 'includeCost' flag exist on the compat endpoint?
r = httpx.post(f"{BASE}/v1/messages", headers={"Authorization": f"Bearer {KEY}", "anthropic-version":"2023-06-01"},
    json={"model":"claude-sonnet-5-5","max_tokens":10,"includeCost":True,"messages":[{"role":"user","content":"hi"}]}, timeout=60)
print("includeCost:", r.status_code, r.text[:400])
