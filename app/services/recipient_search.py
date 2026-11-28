"""Recipient lookup shared by the case page and the older case screen."""
from __future__ import annotations

from app.clients.snipeit import SnipeItClient, SnipeItUser
from app.domain.recipient_identity import looks_like_employee_code


async def find_recipient_users(
    client: SnipeItClient, query: str, *, limit: int = 10
) -> list[SnipeItUser]:
    """Snipe-IT users for a typed query; an exact employee code comes first."""
    text = query.strip()
    exact: list[SnipeItUser] = []
    if looks_like_employee_code(text):
        found = await client.find_user_by_employee_num(text)
        if found is not None:
            exact = [found]
    others = await client.search_users(text, limit=limit)
    seen = {user.id for user in exact}
    return [*exact, *(user for user in others if user.id not in seen)]
