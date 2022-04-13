from discord_slash import cog_ext, SlashContext

from balancebot.common import utils
from balancebot.api import dbutils
from balancebot.api.database import session
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.bot.cogs.cogbase import CogBase
from balancebot.common.utils import create_yes_no_button_row


class UserCog(CogBase):

    @cog_ext.cog_slash(
        name="delete",
        description="Deletes everything associated to you.",
        options=[]
    )
    @utils.log_and_catch_errors()
    async def delete_all(self, ctx: SlashContext):
        user = dbutils.get_user(ctx.author_id)

        def confirm_delete(ctx):
            for client in user.clients:
                dbutils.delete_client(client, self.messenger, commit=False)
            session.query(DiscordUser).filter_by(id=user.id).delete()
            session.commit()

        button_row = create_yes_no_button_row(
            slash=self.slash_cmd_handler,
            author_id=ctx.author_id,
            yes_callback=confirm_delete,
            yes_message="Successfully deleted all your data",
            hidden=True
        )

        await ctx.send('Do you really want to delete **all your accounts**? This action is unreversable.',
                       components=[button_row],
                       hidden=True)

    @cog_ext.cog_slash(
        name="info",
        description="Shows your stored information",
        options=[]
    )
    @utils.log_and_catch_errors()
    async def info(self, ctx):
        user = dbutils.get_user(ctx.author_id)
        await ctx.send(content='', embeds=user.get_discord_embed(), hidden=True)


