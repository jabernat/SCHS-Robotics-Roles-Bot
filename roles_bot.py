#!/usr/bin/env python3
"""Starts the SCHS-Robotics-Roles-Bot that logs into Discord and answers
commands until closed.
"""


__version__ = '0.0.1'

__authors__ = ['James Abernathy']
__copyright__ = 'Copyright © 2023 James Abernathy'
__license__ = 'MIT'


import discord as _discord
import os as _os




class RolesBotClient(_discord.Client):
    """Discord bot client that connects to servers and responds to user app
    commands.
    """

    async def on_ready(self):
        print(f'Logged on as {self.user}.')




def main(
) -> None:
    """Entry point that logs the bot into Discord and executes commands until
    closed.
    """
    try:
        bot_token = _os.environ['SCHS_ROBOTICS_ROLES_BOT_TOKEN']
    except KeyError:
        import getpass
        bot_token = getpass.getpass(prompt='Bot token (input hidden): ')

    client = RolesBotClient(
        intents=_discord.Intents(members=True),
        chunk_guilds_at_startup=False)
    client.run(token=bot_token)




if __name__ == '__main__':
    main()
