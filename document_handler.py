import io
import re

import fitz
import httpx
from bs4 import BeautifulSoup

URL_REGEX = re.compile(r"https?://[^\s<>\"']+")


def extract_urls(text: str) -> list[str]:
    return URL_REGEX.findall(text)


async def extract_text_from_pdf(file_bytes: bytes) -> str:
    doc = fitz.open(stream=io.BytesIO(file_bytes), filetype="pdf")
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    text = "\n".join(pages)
    return _clean_text(text)


async def extract_text_from_url(url: str) -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.find("body")
    text = main.get_text(separator="\n") if main else soup.get_text(separator="\n")
    return _clean_text(text)


async def extract_text_from_urls(text: str) -> str:
    urls = extract_urls(text)
    if not urls:
        return text

    parts = [text]
    for url in urls:
        try:
            content = await extract_text_from_url(url)
            header = f"\n\n--- Contenu extrait de : {url} ---\n"
            parts.append(header + content)
        except Exception:
            parts.append(f"\n\n[Impossible de recuperer le contenu de : {url}]")

    return "\n".join(parts)


def _clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
