"""Factory 3 publishing targets: GitHub + Hugging Face.

Why these two and not a storefront
----------------------------------
Factory 1 sells on Whop (payout to Iran unverified). Factory 2 relied on
affiliate programmes that must accept you first. Factory 3 deliberately
depends on **neither**: GitHub and Hugging Face let anyone publish, today,
with no approval, no marketplace review and no payout relationship.

The asset is a developer dataset/tool. Money arrives two ways, both of which
work under sanctions:
  * **zaps** — Lightning address in every README
  * **sponsors** — a FUNDING.yml pointing at the Lightning address

Neither requires permission from a payment processor.

All calls verified live 2026-09-04: repo create 201, file push 201,
topics 200, HF commit 200.
"""
from __future__ import annotations

import base64
import json
import os

from dist_core import env, http, jbody

GH_API = "https://api.github.com"
HF_API = "https://huggingface.co/api"


def _gh_headers() -> dict:
    return {"Authorization": f"Bearer {env('F3_GH_TOKEN', 'GH_TOKEN')}",
            "Accept": "application/vnd.github+json"}


# ------------------------------------------------------------- GitHub ---
def ensure_repo(name: str, description: str, topics: list[str]) -> dict:
    """Create (or reuse) a public repo. Idempotent — 422 means it exists."""
    owner = env("F3_GH_OWNER", "GITHUB_REPOSITORY").split("/")[0] or "simalidudu-boop"
    code, text = http("POST", f"{GH_API}/user/repos", headers=_gh_headers(),
                      json_body={"name": name, "description": description[:350],
                                 "private": False, "auto_init": True,
                                 "has_issues": True, "has_wiki": False})
    existed = code == 422
    if code not in (201, 422):
        return {"ok": False, "error": f"repo create http_{code}: {text[:150]}"}

    # topics are how anyone finds a repo — set them every time
    http("PUT", f"{GH_API}/repos/{owner}/{name}/topics", headers=_gh_headers(),
         json_body={"names": [t.lower().replace(" ", "-")[:35]
                              for t in topics][:20]})
    return {"ok": True, "owner": owner, "name": name, "existed": existed,
            "url": f"https://github.com/{owner}/{name}"}


def put_file(owner: str, repo: str, path: str, content: str,
             message: str = "add") -> dict:
    """Create or update a file. Handles the update case (needs the blob sha)."""
    url = f"{GH_API}/repos/{owner}/{repo}/contents/{path}"
    sha = None
    code, text = http("GET", url, headers=_gh_headers())
    if code == 200:
        sha = jbody(text).get("sha")

    body = {"message": message,
            "content": base64.b64encode(content.encode()).decode()}
    if sha:
        body["sha"] = sha
    code, text = http("PUT", url, headers=_gh_headers(), json_body=body)
    if code in (200, 201):
        return {"ok": True, "path": path}
    return {"ok": False, "error": f"put {path} http_{code}: {text[:120]}"}


def add_funding(owner: str, repo: str) -> dict:
    """FUNDING.yml — GitHub renders a Sponsor button from this.

    GitHub Sponsors itself cannot pay Iran, so `custom:` points at our own
    zap page instead. That link works from anywhere.
    """
    ln = env("LIGHTNING_ADDRESS")
    page = env("F3_PAGE_BASE", "PACK_PAGE_BASE").rstrip("/")
    urls = [u for u in (f"{page}/p" if page else "", ) if u]
    if not (ln or urls):
        return {"ok": False, "error": "nothing to fund with"}
    lines = ["# Lightning is the only payout rail that works from our region.",
             f"# Zap: {ln}" if ln else ""]
    if urls:
        lines.append(f"custom: [{', '.join(urls)}]")
    return put_file(owner, repo, ".github/FUNDING.yml",
                    "\n".join(x for x in lines if x) + "\n",
                    "add funding")


# -------------------------------------------------------- Hugging Face ---
def publish_hf_dataset(slug: str, readme: str, files: dict) -> dict:
    """Create/refresh a HF dataset repo and commit README + data files.

    NOTE: the legacy `/upload/{rev}/{path}` endpoint is RETIRED (410). The
    NDJSON `/commit/{rev}` endpoint is the only working path.
    """
    user = env("F3_HF_USER", "HF_USER") or "SharkSkin"
    tok = env("F3_HF_TOKEN", "HF_TOKEN")
    if not tok:
        return {"ok": False, "error": "no HF token"}
    repo = f"{user}/{slug}"
    hdr = {"Authorization": f"Bearer {tok}"}

    code, text = http("POST", f"{HF_API}/repos/create", headers=hdr,
                      json_body={"type": "dataset", "name": slug,
                                 "private": False})
    if code not in (200, 201, 409):
        return {"ok": False,
                "error": f"hf create http_{code}: {text[:140]}"}

    lines = [json.dumps({"key": "header",
                         "value": {"summary": f"publish {slug}"}})]
    payload = {"README.md": readme, **files}
    for path, content in payload.items():
        lines.append(json.dumps({"key": "file", "value": {
            "path": path, "encoding": "base64",
            "content": base64.b64encode(content.encode()).decode()}}))

    code, text = http("POST", f"{HF_API}/datasets/{repo}/commit/main",
                      headers={**hdr, "Content-Type": "application/x-ndjson"},
                      data=("\n".join(lines) + "\n").encode())
    if code == 200 and jbody(text).get("success"):
        return {"ok": True, "repo": repo,
                "url": f"https://huggingface.co/datasets/{repo}"}
    return {"ok": False, "error": f"hf commit http_{code}: {text[:140]}"}
