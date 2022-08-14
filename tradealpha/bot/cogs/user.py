from discord_slash import cog_ext, SlashContext

from tradealpha.common.dbasync import db_del_filter, async_session
from tradealpha.common.dbmodels.client import Client
from tradealpha.common import dbutils
from tradealpha.bot import utils
from tradealpha.common.dbmodels.discorduser import DiscordUser
from tradealpha.bot.cogs.cogbase import CogBase


class UserCog(CogBase):

    @cog_ext.cog_slash(
        name="delete",
        description="Deletes everything associated to you.",
        options=[]
    )
    @utils.log_and_catch_errors()
    async def delete_all(self, ctx: SlashContext):
        user = await dbutils.get_discord_user(ctx.author_id, eager_loads=[DiscordUser.clients])

        async def confirm_delete(ctx):
            for client in user.clients:
                await dbutils.delete_client(client, self.messenger, async_session)
            await db_del_filter(DiscordUser, id=user.id)
            await async_session.commit()

        button_row = utils.create_yes_no_button_row(
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
    async def info(self, ctx: SlashContext):
        user = await dbutils.get_discord_user(
            ctx.author_id,
            eager_loads=[(DiscordUser.clients, Client.events)]
        )
        embeds = await user.get_discord_embed()
        await ctx.send(content='', embeds=embeds, hidden=True)


