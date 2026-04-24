import asyncio
import logging

from openai import OpenAI

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MAX_TOKENS,
    DEEPSEEK_MODEL,
    DEEPSEEK_MODEL_FLASH,
    DEEPSEEK_TEMPERATURE,
    MAX_HISTORY_MESSAGES,
)
from database import get_history, save_message, get_user_model
from system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

KEYWORD_PROMPT = """Tu es un assistant qui extrait des mots-cles de recherche a partir d'une question en langage naturel.

Regle : la question peut contenir plusieurs dimensions geographiques ou thematiques. Tu dois toutes les capturer.

Reponds UNIQUEMENT avec ce format, rien d'autre :
PUBMED: [mots-cles en anglais, optimises pour PubMed avec operateurs boolean si utile]
HAL: [mots-cles en francais, optimises pour HAL]
SCHOLAR: [mots-cles en anglais, pour recherche academique large sur Semantic Scholar]
DDG: [requete en anglais, naturelle, pour recherche web generaliste sur DuckDuckGo]

Exemples :

Question : "Peux tu me donner un article sur la prevalence du TDAH en France et dans le monde ?"
PUBMED: ADHD prevalence France worldwide epidemiology global
HAL: TDAH prevalence France monde epidemiologie mondiale
SCHOLAR: ADHD prevalence rates global epidemiology cross-country comparison
DDG: ADHD prevalence France worldwide epidemiology statistics

Question : "Quels sont les traitements non pharmacologiques du TDAH chez les enfants ?"
PUBMED: ADHD non-pharmacological treatment children behavioral therapy intervention
HAL: TDAH traitement non pharmacologique enfants therapie comportementale
SCHOLAR: ADHD children non-pharmacological interventions behavioral therapy efficacy
DDG: ADHD children non-drug treatment behavioral therapy research

Question : "{query}"
"""


def _resolve_model(chat_id: int, requested_model: str | None = None) -> str:
    if requested_model:
        return requested_model
    user_model = get_user_model(chat_id)
    return user_model or DEEPSEEK_MODEL


async def chat(
    chat_id: int,
    user_message: str,
    model: str | None = None,
    system_override: str | None = None,
) -> str:
    resolved_model = _resolve_model(chat_id, model)

    save_message(chat_id, "user", user_message)

    history = get_history(chat_id, limit=MAX_HISTORY_MESSAGES)
    system_content = system_override or SYSTEM_PROMPT
    messages = [{"role": "system", "content": system_content}] + history

    try:
        response = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=DEEPSEEK_TEMPERATURE,
            max_tokens=DEEPSEEK_MAX_TOKENS,
        )
        assistant_message = response.choices[0].message.content or ""
    except Exception as e:
        return f"Erreur lors de l'appel a DeepSeek ({resolved_model}) : {e}"

    save_message(chat_id, "assistant", assistant_message)

    return assistant_message


async def extract_keywords(query: str) -> dict[str, str]:
    prompt = KEYWORD_PROMPT.format(query=query)
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=DEEPSEEK_MODEL_FLASH,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        text = response.choices[0].message.content or ""
    except Exception as e:
        logger.error("Erreur extraction mots-cles: %s", e)
        return {"pubmed": query, "hal": query, "scholar": query, "ddg": query}

    keywords = {"pubmed": query, "hal": query, "scholar": query, "ddg": query}

    for line in text.strip().split("\n"):
        line = line.strip()
        upper = line.upper()
        if upper.startswith("PUBMED:"):
            keywords["pubmed"] = line[7:].strip()
        elif upper.startswith("HAL:"):
            keywords["hal"] = line[4:].strip()
        elif upper.startswith("SCHOLAR:"):
            keywords["scholar"] = line[8:].strip()
        elif upper.startswith("DDG:"):
            keywords["ddg"] = line[4:].strip()

    return keywords
