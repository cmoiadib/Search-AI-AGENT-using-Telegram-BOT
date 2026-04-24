import re


def md_to_html(text: str) -> str:
    text = _convert_bold(text)
    text = _convert_blockquotes(text)
    text = _convert_arrows(text)
    text = _clean_remaining_md(text)
    text = _escape_unsafe_html(text)
    return text.strip()


def _convert_bold(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    return text


def _convert_blockquotes(text: str) -> str:
    lines = text.split("\n")
    result = []
    in_quote = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("> ") or stripped.startswith(">"):
            content = stripped.lstrip("> ").strip()
            if content:
                if not in_quote:
                    result.append("<blockquote>")
                    in_quote = True
                result.append(content)
            continue
        if in_quote:
            result.append("</blockquote>")
            in_quote = False
        result.append(line)

    if in_quote:
        result.append("</blockquote>")

    return "\n".join(result)


def _convert_arrows(text: str) -> str:
    bullet = "\u2022"
    text = re.sub(r"^(\s*)->\s+", rf"\1  {bullet} ", text, flags=re.MULTILINE)
    return text


def _clean_remaining_md(text: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _escape_unsafe_html(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    text = text.replace("&lt;b&gt;", "<b>")
    text = text.replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;i&gt;", "<i>")
    text = text.replace("&lt;/i&gt;", "</i>")
    text = text.replace("&lt;code&gt;", "<code>")
    text = text.replace("&lt;/code&gt;", "</code>")
    text = text.replace("&lt;pre&gt;", "<pre>")
    text = text.replace("&lt;/pre&gt;", "</pre>")
    text = text.replace("&lt;blockquote&gt;", "<blockquote>")
    text = text.replace("&lt;/blockquote&gt;", "</blockquote>")
    text = text.replace("&lt;a\s+href=&quot;", '<a href="')
    text = text.replace("&quot;&gt;", '">')
    text = text.replace("&lt;/a&gt;", "</a>")

    return text


def split_message(text: str, max_len: int = 4096) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        cut = text.rfind("\n\n", 0, max_len)
        if cut == -1 or cut < max_len // 2:
            cut = text.rfind("\n", 0, max_len)
        if cut == -1 or cut < max_len // 2:
            cut = text.rfind(" ", 0, max_len)
        if cut == -1:
            cut = max_len

        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n ")

        chunks[-1] = _close_open_tags(chunks[-1])

    return chunks


def _close_open_tags(text: str) -> str:
    opens = len(re.findall(r"<(b|i|code|pre|blockquote)>", text))
    closes = len(re.findall(r"</(b|i|code|pre|blockquote)>", text))
    diff = opens - closes

    if diff <= 0:
        return text

    tags = re.findall(r"<(b|i|code|pre|blockquote)>", text)
    open_tags = []
    for tag in tags:
        open_tags.append(tag)

    close_tags = re.findall(r"</(b|i|code|pre|blockquote)>", text)
    for tag in close_tags:
        if tag in open_tags:
            open_tags.remove(tag)

    for tag in reversed(open_tags):
        text += f"</{tag}>"

    return text
