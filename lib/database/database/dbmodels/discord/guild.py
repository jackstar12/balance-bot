from database.dbmodels.mixins.serializer import Serializer

from database.dbsync import Base, BaseMixin
from sqlalchemy.orm import relationship, backref
from sqlalchemy importString, BigInteger, Enum

from database.enums import Tier


class Guild(Base, Serializer, BaseMixin):
    __tablename__ = 'guild'

    id = mapped_column(BigInteger, primary_key=True, nullable=False)
    name = mapped_column(String, nullable=True)
    tier = mapped_column(Enum(Tier), default=Tier.BASE, nullable=False)
    avatar = mapped_column(String, nullable=True)

    events = relationship('Event',
                          lazy='raise',
                          backref=backref('guild', lazy='raise'),
                          viewonly=True,
                          primaryjoin='Guild.id == foreign(Event.guild_id)')

    users = relationship('DiscordUser',
                         secondary='guild_association',
                         lazy='raise',
                         backref=backref('guilds', lazy='raise'),
                         viewonly=True)

    associations = relationship('GuildAssociation',
                                lazy='raise',
                                viewonly=True,
                                back_populates='guild')
