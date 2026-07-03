"""Text-cleaning helpers shared by fetchers.

Currently houses ``strip_em_tags`` — used by both EastMoneyFetcher and
ThsFetcher to remove ``<em>...</em>`` highlight tags from upstream news
titles and snippets. Both fetchers had identical copies of this helper
(``_strip_em``); see Task #55 in the audit task list.
"""


def strip_em_tags(s: str) -> str:
    """Strip ``<em>`` / ``</em>`` highlight tags from ``s``.

    Also removes the parenthesized variant ``(<em>...</em>)`` which
    upstream sometimes returns inside title/content snippets.

    Used by EastMoneyFetcher and ThsFetcher news normalisation.
    """
    return s.replace("(<em>", "").replace("</em>)", "").replace("<em>", "").replace("</em>", "")