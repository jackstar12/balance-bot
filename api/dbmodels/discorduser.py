from api.database import db
import discord


class DiscordUser(db.Model):
    __tablename__ = 'discorduser'
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.Integer(), nullable=False)
    name = db.Column(db.String(), nullable=False)
    global_client_id = db.Column(db.Integer, nullable=True)
    clients = db.relationship('Client', backref='discorduser', lazy=True, uselist=True)

    def get_discord_embed(self):
        # client = None
        # for cur_client in self.clients:
        #     if cur_client.event_id and guild_id:
        #         if cur_client.event.guild_id == guild_id:
        #             client = cur_client
        #     elif cur_client.event_id:
        #         client = cur_client

        embed = discord.Embed(title="User Information")

        for client in self.clients:

            events = ''

            for event in client.events:
                events += f'{event.name}, '
            events += 'Global, ' if self.global_client_id == client.id else ''

            embed = discord.Embed(title="User Information")
            embed.add_field(name='Event', value=events, inline=False)
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
