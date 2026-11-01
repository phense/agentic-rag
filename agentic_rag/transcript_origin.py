"""Distinguish conversation records from generated native-host context.

Native transcript message.role describes model input, not necessarily its
author. Claude compaction summaries, metadata and API request mirrors must
never become original human evidence merely because that role is 'user'.
"""
from .transcript_agy import is_step


def conversation_record(event: dict) -> bool:
    if event.get('isCompactSummary') or event.get('isMeta'):
        return False
    # Older supported exports have no outer type. Unknown typed diagnostic
    # records fail closed; their raw bytes and cursor positions are retained.
    return is_step(event) or event.get('type') in (None, 'user', 'assistant', 'response_item')
