import asyncio
import logging
import time
from collections import defaultdict

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from config import (
    DEEPSEEK_MODEL,
    DEEPSEEK_MODEL_FLASH,
    RATE_LIMIT_MESSAGES,
    RATE_LIMIT_SECONDS,
    TELEGRAM_BOT_TOKEN,
)
from database import (
    clear_history,
    delete_analysis,
    get_analysis,
    get_last_assistant_message,
    get_saved_analyses,
    get_user_model,
    init_db,
    save_analysis,
    set_user_model,
)
from deepseek_client import chat, extract_keywords
from ddg import format_ddg_results, search_ddg
from document_handler import (
    extract_text_from_pdf,
    extract_text_from_urls,
    extract_urls,
)
from formatter import md_to_html, split_message
from hal import format_hal_results, search_hal
from pubmed import format_results as format_pubmed_results, search_articles
from scholar import format_scholar_results, search_scholar
from system_prompt import RESEARCH_SYSTEM_OVERRIDE

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_user_timestamps: dict[int, list[float]] = defaultdict(list)

WELCOME = (
    "<b>AssistTDAH</b> — Assistant de recherche TDAH\n\n"
    "<b>Commandes :</b>\n"
    "  /analyse + texte/PDF — Analyser un article\n"
    "  /recherche + sujet — Chercher sur PubMed + HAL + Scholar + DDG\n"
    "  /synthese — Comparer des sources\n"
    "  /save — Sauvegarder la derniere analyse\n"
    "  /favoris — Voir les analyses sauvegardees\n"
    "  /delete [numero] — Supprimer un favori\n"
    "  /modele flash|pro — Changer de modele\n"
    "  /reset — Effacer l'historique\n"
    "  /aide — Afficher ce message\n\n"
    "Ou envoyez directement un texte, PDF ou lien."
)


def _check_rate_limit(chat_id: int) -> bool:
    now = time.time()
    timestamps = _user_timestamps[chat_id]
    timestamps[:] = [t for t in timestamps if now - t < RATE_LIMIT_SECONDS]
    if len(timestamps) >= RATE_LIMIT_MESSAGES:
        return False
    timestamps.append(now)
    return True


def _current_model_label(chat_id: int) -> str:
    model = get_user_model(chat_id) or DEEPSEEK_MODEL
    if "flash" in model:
        return "V4 Flash"
    return "V4 Pro"


async def _send_reply(update: Update, text: str) -> None:
    html = md_to_html(text)
    chunks = split_message(html)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await update.message.reply_text(chunk)
            except Exception:
                pass


def _deduplicate_by_doi(
    *source_lists: tuple[str, list[dict]],
) -> list[tuple[list[str], dict]]:
    doi_map: dict[str, int] = {}
    results: list[tuple[list[str], dict]] = []

    for source_name, articles in source_lists:
        for article in articles:
            doi = article.get("doi", "").strip().lower()

            if doi and doi in doi_map:
                idx = doi_map[doi]
                existing_sources, existing_article = results[idx]
                if source_name not in existing_sources:
                    existing_sources.append(source_name)
                if len(article.get("abstract", "")) > len(
                    existing_article.get("abstract", "")
                ):
                    results[idx] = (existing_sources, {**article})
                else:
                    results[idx] = (existing_sources, existing_article)
                continue

            entry = ([source_name], {**article})
            results.append(entry)
            if doi:
                doi_map[doi] = len(results) - 1

    return results


def _format_deduped(
    deduped: list[tuple[list[str], dict]],
) -> tuple[str, dict[str, int]]:
    source_counts: dict[str, int] = {}
    parts = []

    for sources, article in deduped:
        for s in sources:
            source_counts[s] = source_counts.get(s, 0) + 1

        tag = " + ".join(sources)
        lines = [f"ARTICLE [{tag}]"]
        lines.append(f"Titre: {article.get('title', 'Sans titre')}")
        if article.get("authors"):
            lines.append(f"Auteurs: {article['authors']}")
        if article.get("year"):
            lines.append(f"Annee: {article['year']}")
        if article.get("doi"):
            lines.append(f"DOI: {article['doi']}")
        if article.get("url"):
            lines.append(f"Lien: {article['url']}")
        if article.get("abstract") and article["abstract"] != "Abstract non disponible.":
            lines.append(f"Abstract: {article['abstract']}")
        elif article.get("snippet"):
            lines.append(f"Extrait: {article['snippet']}")
        if article.get("citations"):
            lines.append(f"Citations: {article['citations']}")

        parts.append("\n".join(lines))

    combined = "\n\n---\n\n".join(parts)
    return combined, source_counts


async def _send_error(update: Update, text: str) -> None:
    await update.message.reply_text(text)


# --- Command handlers ---


async def start_command(update: Update, _) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def help_command(update: Update, _) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def reset_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    clear_history(chat_id)
    await update.message.reply_text(
        "Historique efface. Nouvelle conversation."
    )


async def analyse_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    if not _check_rate_limit(chat_id):
        await _send_error(update, "Trop de requetes. Patientez quelques instants.")
        return

    text = update.message.text.removeprefix("/analyse").strip()
    if not text:
        await _send_error(
            update,
            "Utilisation : /analyse suivi du texte de l'article, "
            "ou envoyez un PDF puis /analyse.",
        )
        return

    await update.message.chat.send_action("typing")
    response = await chat(chat_id, text)
    await _send_reply(update, response)


async def recherche_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    if not _check_rate_limit(chat_id):
        await _send_error(update, "Trop de requetes. Patientez quelques instants.")
        return

    query = update.message.text.removeprefix("/recherche").strip()
    if not query:
        await _send_error(
            update,
            "Utilisation : /recherche suivi du sujet\n"
            "Exemple : /recherche TDAH adultes traitement pharmacologique",
        )
        return

    await update.message.chat.send_action("typing")

    keywords = await extract_keywords(query)

    pubmed_task = asyncio.create_task(search_articles(keywords["pubmed"]))
    hal_task = asyncio.create_task(search_hal(keywords["hal"]))
    scholar_task = asyncio.create_task(search_scholar(keywords["scholar"]))
    ddg_task = asyncio.create_task(search_ddg(keywords["ddg"]))

    pubmed_articles, hal_articles, scholar_articles, ddg_results = [], [], [], []

    results = await asyncio.gather(
        pubmed_task, hal_task, scholar_task, ddg_task, return_exceptions=True
    )

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            source = ["PubMed", "HAL", "Semantic Scholar", "DuckDuckGo"][i]
            logger.error("Erreur %s: %s", source, result)
        elif i == 0:
            pubmed_articles = result
        elif i == 1:
            hal_articles = result
        elif i == 2:
            scholar_articles = result
        elif i == 3:
            ddg_results = result

    total_raw = (
        len(pubmed_articles) + len(hal_articles)
        + len(scholar_articles) + len(ddg_results)
    )
    if total_raw == 0:
        await _send_error(update, "Aucun article trouve. Essayez avec d'autres mots-cles.")
        return

    deduped = _deduplicate_by_doi(
        ("PUBMED", pubmed_articles),
        ("HAL", hal_articles),
        ("SCHOLAR", scholar_articles),
        ("DDG", ddg_results),
    )

    combined_text, source_counts = _format_deduped(deduped)

    source_summary = ", ".join(
        f"{src}: {cnt}" for src, cnt in source_counts.items()
    )

    user_message = (
        f"Demande de l'utilisateur : {query}\n\n"
        f"{combined_text}\n\n"
        f"Resultats dedoublonnes ({len(deduped)} articles uniques sur {total_raw} bruts) "
        f"— {source_summary}. "
        f"Analyse chaque article, selectionne les 10 plus pertinents "
        f"pour cette demande, et classe-les par pertinence decroissante. "
        f"Si un article apparait dans plusieurs sources, montre TOUS les tags sources."
    )

    await update.message.chat.send_action("typing")
    response = await chat(
        chat_id, user_message, system_override=RESEARCH_SYSTEM_OVERRIDE
    )
    await _send_reply(update, response)


async def synthese_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    if not _check_rate_limit(chat_id):
        await _send_error(update, "Trop de requetes. Patientez quelques instants.")
        return

    text = update.message.text.removeprefix("/synthese").strip()
    if not text:
        await _send_error(
            update,
            "Utilisation : /synthese suivi de votre demande de comparaison\n"
            "Exemple : /synthese Compare les etudes sur le methylphenidate vs atomoxetine",
        )
        return

    await update.message.chat.send_action("typing")
    response = await chat(chat_id, text)
    await _send_reply(update, response)


async def save_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    last_msg = get_last_assistant_message(chat_id)

    if not last_msg:
        await _send_error(update, "Aucune analyse a sauvegarder dans l'historique.")
        return

    title = last_msg[:80].replace("\n", " ").strip() + "..."
    row_id = save_analysis(chat_id, title, last_msg)
    await update.message.reply_text(f"Analyse sauvegardee (#{row_id}).")


async def favoris_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    analyses = get_saved_analyses(chat_id)

    if not analyses:
        await _send_error(update, "Aucune analyse sauvegardee. Utilisez /save pour en ajouter.")
        return

    lines = ["<b>Analyses sauvegardees :</b>\n"]
    for a in analyses:
        lines.append(f"  #{a['id']} — {a['title']}")

    lines.append("\n/delete [numero] pour supprimer")
    lines.append("Envoyez juste le numero pour relire une analyse.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def delete_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.removeprefix("/delete").strip()

    try:
        analysis_id = int(text)
    except ValueError:
        await _send_error(update, "Utilisation : /delete [numero]")
        return

    deleted = delete_analysis(chat_id, analysis_id)
    if deleted:
        await update.message.reply_text(f"Analyse #{analysis_id} supprimee.")
    else:
        await _send_error(update, f"Analyse #{analysis_id} non trouvee.")


async def modele_command(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.removeprefix("/modele").strip().lower()

    if text in ("pro", "v4-pro", "deepseek-v4-pro"):
        set_user_model(chat_id, "deepseek-v4-pro")
        await update.message.reply_text("Modele : <b>DeepSeek V4 Pro</b>", parse_mode=ParseMode.HTML)
    elif text in ("flash", "v4-flash", "deepseek-v4-flash"):
        set_user_model(chat_id, DEEPSEEK_MODEL_FLASH)
        await update.message.reply_text("Modele : <b>DeepSeek V4 Flash</b>", parse_mode=ParseMode.HTML)
    else:
        current = _current_model_label(chat_id)
        await update.message.reply_text(
            f"Modele actuel : <b>{current}</b>\n\n"
            "Utilisation : /modele flash ou /modele pro",
            parse_mode=ParseMode.HTML,
        )


# --- Message handlers ---


async def handle_text(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    if not _check_rate_limit(chat_id):
        await _send_error(update, "Trop de requetes. Patientez quelques instants.")
        return

    user_text = update.message.text

    if user_text.strip().isdigit():
        analysis_id = int(user_text.strip())
        content = get_analysis(chat_id, analysis_id)
        if content:
            await _send_reply(update, content)
            return

    urls = extract_urls(user_text)
    if urls:
        user_text = await extract_text_from_urls(user_text)

    await _process_and_reply(chat_id, user_text, update)


async def handle_document(update: Update, _) -> None:
    chat_id = update.effective_chat.id
    if not _check_rate_limit(chat_id):
        await _send_error(update, "Trop de requetes. Patientez quelques instants.")
        return

    doc = update.message.document
    if not doc:
        return

    if not doc.mime_type or "pdf" not in doc.mime_type:
        await _send_error(
            update, "Seuls les PDF sont supportes. Copiez-collez le texte sinon."
        )
        return

    await update.message.chat.send_action("typing")

    try:
        file = await doc.get_file()
        file_bytes = await file.download_as_bytearray()
        text = await extract_text_from_pdf(bytes(file_bytes))
    except Exception as e:
        logger.error("Erreur extraction PDF: %s", e)
        await _send_error(update, f"Erreur extraction PDF : {e}")
        return

    if not text:
        await _send_error(
            update, "Impossible d'extraire le texte. Essayez de copier-coller."
        )
        return

    await _process_and_reply(chat_id, text, update)


async def _process_and_reply(chat_id: int, user_text: str, update: Update) -> None:
    try:
        await update.message.chat.send_action("typing")
        response = await chat(chat_id, user_text)
    except Exception as e:
        logger.error("Erreur DeepSeek: %s", e)
        await _send_error(update, f"Erreur : {e}")
        return

    await _send_reply(update, response)


# --- Main ---


def main() -> None:
    init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("aide", help_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("analyse", analyse_command))
    app.add_handler(CommandHandler("recherche", recherche_command))
    app.add_handler(CommandHandler("synthese", synthese_command))
    app.add_handler(CommandHandler("save", save_command))
    app.add_handler(CommandHandler("favoris", favoris_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("modele", modele_command))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("AssistTDAH bot demarre (PubMed + HAL + Scholar + DDG + V4 Pro).")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
