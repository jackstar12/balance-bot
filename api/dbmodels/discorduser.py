from api.database import db
import discord


class DiscordUser(db.Model):
    __tablename__ = 'discorduser'
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.Integer(), nullable=False)
    name = db.Column(db.String(), nullable=False)
    client = db.relationship('Client', backref='discorduser', lazy=True, uselist=False)

    def get_discord_embed(self, guild_name: str = None):
        embed = discord.Embed(title="User Information")
        embed.add_field(name='Guild', value=guild_name if guild_name else 'Global', inline=False)
        embed.add_field(name='Exchange', value=self.client.exchange)
        embed.add_field(name='Api Key', value=self.client.api_key)
        embed.add_field(name='Api Secret', value=self.client.api_secret)

        if self.client.subaccount:
            embed.add_field(name='Subaccount', value=self.client.subaccount)
        for extra in self.client.extra_kwargs:
            embed.add_field(name=extra, value=self.client.extra_kwargs[extra])

        if len(self.client.history) > 0:
            embed.add_field(name='Initial Balance', value=self.client.history[0].to_string())

        return embed
