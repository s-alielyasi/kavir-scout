"""A single authorization gate for every supported update."""
from datetime import datetime, timedelta
from telegram import Update
from kavirtire.orchestration.models import AuthorizedOwner


def authorized(update: object, owner: AuthorizedOwner, started_at: datetime) -> bool:
    if not isinstance(update, Update) or update.message is None:
        return False
    user, chat, message = update.effective_user, update.effective_chat, update.message
    if (user is None or chat is None or user.is_bot or chat.type != 'private'
            or type(user.id) is not int or type(chat.id) is not int
            or (user.id, chat.id) != (owner.user_id, owner.chat_id)
            or message.sender_chat is not None or message.forward_origin is not None
            or message.is_automatic_forward or update.edited_message is not None
            or message.date < started_at.replace(microsecond=0)
            or message.date > datetime.now(started_at.tzinfo) + timedelta(seconds=5)):
        return False
    return True
