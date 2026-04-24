import logging

import httpx

from config import HAL_MAX_RESULTS

logger = logging.getLogger(__name__)

HAL_BASE_URL = "https://api.archives-ouvertes.fr/search"

HAL_FIELDS = (
    "docid,title_s,authFullName_s,producedDateY_i,"
    "abstract_s,doiId_s,journal_s,url_s,docType_s"
)


async def search_hal(query: str, max_results: int = HAL_MAX_RESULTS) -> list[dict]:
    params = {
        "q": f"text:{query}",
        "wt": "json",
        "rows": max_results,
        "fl": HAL_FIELDS,
        "sort": "score desc",
        "fq": "submitType_s:file",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(HAL_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    docs = data.get("response", {}).get("docs", [])
    articles = []
    for doc in docs:
        article = _parse_doc(doc)
        if article:
            articles.append(article)
    return articles


def _parse_doc(doc: dict) -> dict | None:
    titles = doc.get("title_s", [])
    title = titles[0] if titles else "Sans titre"

    authors = doc.get("authFullName_s", [])
    authors_str = ", ".join(authors[:6])
    if len(authors) > 6:
        authors_str += " et al."

    year = doc.get("producedDateY_i", "")
    if year:
        year = str(year)

    abstracts = doc.get("abstract_s", [])
    abstract = abstracts[0] if abstracts else "Abstract non disponible."

    doi = doc.get("doiId_s", "")

    journal_list = doc.get("journal_s", [])
    journal = ""
    if isinstance(journal_list, list):
        journal = journal_list[0] if journal_list else ""
    elif isinstance(journal_list, str):
        journal = journal_list

    doc_type_raw = doc.get("docType_s", "")
    type_map = {
        "ART": "Article",
        "COMM": "Communication",
        "COUV": "Chapitre d'ouvrage",
        "OUV": "Ouvrage",
        "DOUV": "Direction d'ouvrage",
        "THESE": "These",
        "HDR": "HDR",
        "REPORT": "Rapport",
        "UNDEFINED": "Autre",
        "OTHER": "Autre",
    }
    doc_type = type_map.get(doc_type_raw, doc_type_raw)

    docid = doc.get("docid", "")
    url = f"https://hal.archives-ouvertes.fr/{docid}" if docid else ""

    return {
        "title": title,
        "authors": authors_str,
        "year": year,
        "journal": journal,
        "abstract": abstract,
        "doi": doi,
        "url": url,
        "doc_type": doc_type,
        "source": "HAL",
    }


def format_hal_results(articles: list[dict]) -> str:
    if not articles:
        return "Aucun article trouve sur HAL pour cette recherche."

    parts = [f"Resultats HAL ({len(articles)} articles):\n"]
    for i, a in enumerate(articles, 1):
        block = f"ARTICLE HAL-{i}\n"
        block += f"Titre: {a['title']}\n"
        block += f"Auteurs: {a['authors']}\n"
        block += f"Annee: {a['year']}\n"
        if a["journal"]:
            block += f"Revue: {a['journal']}\n"
        if a["doi"]:
            block += f"DOI: {a['doi']}\n"
        if a["url"]:
            block += f"Lien: {a['url']}\n"
        if a["doc_type"]:
            block += f"Type: {a['doc_type']}\n"
        block += f"Abstract: {a['abstract']}\n"
        parts.append(block)

    return "\n---\n".join(parts)
