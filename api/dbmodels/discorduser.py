from api.database import db
import discord
from api.dbmodels.serializer import Serializer


class DiscordUser(db.Model, Serializer):
    __tablename__ = 'discorduser'
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.Integer(), nullable=False)
    name = db.Column(db.String(), nullable=False)

    global_client_id = db.Column(db.Integer(), db.ForeignKey('client.id'))
    global_client = db.relationship('Client', lazy=True, foreign_keys=global_client_id, post_update=True, uselist=False)

    clients = db.relationship('Client', backref='discorduser', lazy=True, uselist=True, foreign_keys='[Client.discord_user_id]')

    def get_discord_embed(self):

        embed = discord.Embed(title="User Information")

        for client in self.clients:
            embed = discord.Embed(title="User Information")
            embed.add_field(name='Event', value=client.get_event_string(), inline=False)
            embed.add_field(name='Exchange', value=client.exchange)
            embed.add_field(name='Api Key', value=client.api_key)
            embed.add_field(name='Api Secret', value=client.api_secret)

            if client.subaccount:
                embed.add_field(name='Subaccount', value=client.subaccount)
            for extra in client.extra_kwargs:
                embed.add_field(name=extra, value=client.extra_kwargs[extra])

            if len(client.history) > 0:
                embed.add_field(name='Initial Balance', value=client.history[0].to_string())

        return embed
