import logging
import xml.etree.ElementTree as ET

import httpx

from config import PUBMED_BASE_URL, PUBMED_MAX_RESULTS

logger = logging.getLogger(__name__)


async def search_articles(query: str, max_results: int = PUBMED_MAX_RESULTS) -> list[dict]:
    pmids = await _esearch(query, max_results)
    if not pmids:
        return []
    articles = await _efetch(pmids)
    return articles


async def _esearch(query: str, max_results: int) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{PUBMED_BASE_URL}/esearch.fcgi", params=params)
        resp.raise_for_status()
        data = resp.json()

    result = data.get("esearchresult", {})
    id_list = result.get("idlist", [])
    return id_list


async def _efetch(pmids: list[str]) -> list[dict]:
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{PUBMED_BASE_URL}/efetch.fcgi", params=params)
        resp.raise_for_status()

    return _parse_articles(resp.text)


def _parse_articles(xml_text: str) -> list[dict]:
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.error("Erreur parsing XML PubMed")
        return articles

    for article_elem in root.findall(".//PubmedArticle"):
        article = _extract_article(article_elem)
        if article:
            articles.append(article)

    return articles


def _extract_article(elem: ET.Element) -> dict | None:
    medline = elem.find(".//MedlineCitation")
    if medline is None:
        return None

    article_data = medline.find("Article")
    if article_data is None:
        return None

    title_elem = article_data.find(".//ArticleTitle")
    title = title_elem.text if title_elem is not None and title_elem.text else "Sans titre"

    authors = _extract_authors(article_data)

    journal_elem = article_data.find(".//Journal/Title")
    journal = journal_elem.text if journal_elem is not None and journal_elem.text else ""

    year_elem = article_data.find(".//PubDate/Year")
    medline_date = article_data.find(".//PubDate/MedlineDate")
    year = ""
    if year_elem is not None and year_elem.text:
        year = year_elem.text
    elif medline_date is not None and medline_date.text:
        year = medline_date.text[:4]

    abstract_parts = []
    for abs_elem in article_data.findall(".//AbstractText"):
        label = abs_elem.get("Label", "")
        text = "".join(abs_elem.itertext()).strip()
        if text:
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
    abstract = "\n".join(abstract_parts) if abstract_parts else "Abstract non disponible."

    pmid_elem = medline.find("PMID")
    pmid = pmid_elem.text if pmid_elem is not None else ""

    doi = ""
    for aid in elem.findall(".//ArticleId"):
        if aid.get("IdType") == "doi":
            doi = aid.text or ""
            break

    pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "abstract": abstract,
        "doi": doi,
        "pmid": pmid,
        "url": pubmed_url,
    }


def _extract_authors(article_data: ET.Element) -> str:
    author_list = article_data.findall(".//AuthorList/Author")
    names = []
    for author in author_list[:6]:
        last = author.find("LastName")
        initials = author.find("Initials")
        if last is not None and last.text:
            name = last.text
            if initials is not None and initials.text:
                name += f" {initials.text}"
            names.append(name)
    if len(author_list) > 6:
        names.append("et al.")
    return ", ".join(names)


def format_results(articles: list[dict]) -> str:
    if not articles:
        return "Aucun article trouve sur PubMed pour cette recherche."

    parts = [f"Resultats PubMed ({len(articles)} articles trouves):\n"]
    for i, a in enumerate(articles, 1):
        block = (
            f"ARTICLE {i}\n"
            f"Titre: {a['title']}\n"
            f"Auteurs: {a['authors']}\n"
            f"Annee: {a['year']}\n"
            f"Revue: {a['journal']}\n"
        )
        if a["doi"]:
            block += f"DOI: {a['doi']}\n"
        if a["url"]:
            block += f"Lien: {a['url']}\n"
        block += f"Abstract: {a['abstract']}\n"
        parts.append(block)

    return "\n---\n".join(parts)
