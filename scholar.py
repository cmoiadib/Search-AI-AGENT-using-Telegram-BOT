import logging

import httpx

from config import SCHOLAR_MAX_RESULTS

logger = logging.getLogger(__name__)

SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SCHOLAR_FIELDS = "title,authors,year,abstract,externalIds,url,citationCount"


async def search_scholar(query: str, max_results: int = SCHOLAR_MAX_RESULTS) -> list[dict]:
    params = {
        "query": query,
        "limit": max_results,
        "fields": SCHOLAR_FIELDS,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(SCHOLAR_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("Erreur Semantic Scholar: %s", e)
        return []

    papers = data.get("data", [])
    articles = []
    for paper in papers:
        article = _parse_paper(paper)
        if article:
            articles.append(article)
    return articles


def _parse_paper(paper: dict) -> dict | None:
    if not paper:
        return None

    title = paper.get("title", "") or "Sans titre"

    author_list = paper.get("authors", [])
    names = []
    for a in author_list[:6]:
        name = a.get("name", "")
        if name:
            names.append(name)
    if len(author_list) > 6:
        names.append("et al.")
    authors_str = ", ".join(names)

    year = paper.get("year")
    year_str = str(year) if year else ""

    abstract = paper.get("abstract") or "Abstract non disponible."

    ext_ids = paper.get("externalIds") or {}
    doi = ext_ids.get("DOI", "") or ""

    url = paper.get("url", "") or ""
    citations = paper.get("citationCount") or 0

    return {
        "title": title,
        "authors": authors_str,
        "year": year_str,
        "abstract": abstract,
        "doi": doi,
        "url": url,
        "citations": citations,
        "source": "SCHOLAR",
    }


def format_scholar_results(articles: list[dict]) -> str:
    if not articles:
        return "Aucun article trouve sur Semantic Scholar pour cette recherche."

    parts = [f"Resultats Semantic Scholar ({len(articles)} articles):\n"]
    for i, a in enumerate(articles, 1):
        block = f"ARTICLE SCHOLAR-{i}\n"
        block += f"Titre: {a['title']}\n"
        block += f"Auteurs: {a['authors']}\n"
        block += f"Annee: {a['year']}\n"
        if a["doi"]:
            block += f"DOI: {a['doi']}\n"
        if a["url"]:
            block += f"Lien: {a['url']}\n"
        if a["citations"]:
            block += f"Citations: {a['citations']}\n"
        block += f"Abstract: {a['abstract']}\n"
        parts.append(block)

    return "\n---\n".join(parts)
