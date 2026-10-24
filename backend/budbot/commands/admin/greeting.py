"""Show or update the existing greeting/override."""

from budbot.commands.admin.common import assistant_field


async def greeting(context, parsed):
    return await assistant_field(context, parsed, "greeting")
