"""Show or update the existing assistant name/override."""

from budbot.commands.admin.common import assistant_field


async def bot_name(context, parsed):
    return await assistant_field(context, parsed, "display_name")
