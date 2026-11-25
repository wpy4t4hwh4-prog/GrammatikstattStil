"""Exportiert alle Dokumente der Research-Ablage als Markdown ins Repo (research-ablage-export/).

RDM/Backup: Die Ablage lebt in der Mistral-Cloud; dieser Export macht sie versioniert,
zitierbar und plattformunabhaengig. Lauf: woechentlich via .github/workflows/ablage-export.yml.
"""
import asyncio
import os
import re
import sys

from mistralai.workflows.client import get_mistral_client

NOTES_LIBRARY_ID = "01a1b7a7-d3b3-7603-9601-7efb317d38ee"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research-ablage-export")


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return (s or "dokument")[:120]


async def main() -> int:
    key = os.getenv("MISTRAL_API_KEY")
    if not key:
        print("MISTRAL_API_KEY fehlt", file=sys.stderr)
        return 2
    client = get_mistral_client(api_key=key)
    os.makedirs(OUT_DIR, exist_ok=True)
    docs = []
    page = 0
    while page < 50:
        listing = await client.beta.libraries.documents.list_async(library_id=NOTES_LIBRARY_ID, page_size=100, page=page)
        data = listing.data or []
        docs.extend(data)
        if len(data) < 100:
            break
        page += 1
    written = 0
    for d in docs:
        name = d.name or f"{d.id}.md"
        try:
            content = await client.beta.libraries.documents.text_content_async(library_id=NOTES_LIBRARY_ID, document_id=d.id)
            text = getattr(content, "text", None) or str(content)
        except Exception as e:
            print(f"SKIP {name}: {e}", file=sys.stderr)
            continue
        header = f"<!-- exportiert aus Research-Ablage (Agent) | document_id: {d.id} | status: {d.processing_status} -->\n\n"
        path = os.path.join(OUT_DIR, _slug(name if name.endswith(".md") else name + ".md"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + text)
        written += 1
    print(f"EXPORT OK: {written}/{len(docs)} Dokumente nach {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
