import asyncio
import logging

from ddgs import DDGS

from config import DDG_MAX_RESULTS

logger = logging.getLogger(__name__)


async def search_ddg(query: str, max_results: int = DDG_MAX_RESULTS) -> list[dict]:
    try:
        results = await asyncio.to_thread(
            _ddg_search, query, max_results
        )
    except Exception as e:
        logger.error("Erreur DuckDuckGo: %s", e)
        return []
    return results


def _ddg_search(query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        raw = ddgs.text(query, max_results=max_results)
    articles = []
    for r in raw:
        article = {
            "title": r.get("title", "") or "Sans titre",
            "url": r.get("href", ""),
            "snippet": r.get("body", "") or "Extrait non disponible.",
            "doi": "",
            "abstract": "",
            "authors": "",
            "year": "",
            "source": "DDG",
        }
        articles.append(article)
    return articles


def format_ddg_results(results: list[dict]) -> str:
    if not results:
        return "Aucun resultat trouve sur DuckDuckGo pour cette recherche."

    parts = [f"Resultats DuckDuckGo ({len(results)} resultats web):\n"]
    for i, r in enumerate(results, 1):
        block = f"RESULTAT DDG-{i}\n"
        block += f"Titre: {r['title']}\n"
        block += f"Lien: {r['url']}\n"
        block += f"Extrait: {r['snippet']}\n"
        parts.append(block)

    return "\n---\n".join(parts)
