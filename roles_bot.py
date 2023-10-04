#!/usr/bin/env python3
"""Starts the SCHS-Robotics-Roles-Bot that logs into Discord and answers
commands until closed.
"""


__version__ = '0.0.1'

__authors__ = ['James Abernathy']
__copyright__ = 'Copyright © 2023 James Abernathy'
__license__ = 'MIT'


import discord as _discord
import logging as _logging
import os as _os




class RolesBotClient(_discord.Client):
    """Discord bot client that connects to servers and responds to user app
    commands.
    """

    _logger: _logging.Logger

    _slash_commands: _discord.app_commands.CommandTree
    """Tree of available slash commands."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs,
            intents=_discord.Intents(
                members=True,  # Allow querying all guild members
                guilds=True),  # Receive on_guild_available events
            chunk_guilds_at_startup=False)

        self._logger = _logging.getLogger(
            f'{_discord.__name__}.{type(self).__name__}')
        self._slash_commands = _discord.app_commands.CommandTree(self,
            fallback_to_global=False)

    async def on_ready(self) -> None:
        """Triggers once connected in and caches have pre-populated."""
        await self._slash_commands.sync()  # Global commands only
        self._logger.info(f'Logged on as {self.user}.')

    async def on_guild_available(self,
        guild: _discord.Guild
    ) -> None:
        """Registers slash commands with the server."""

        # /roles_help
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_help(
            interaction: _discord.Interaction
        ) -> None:
            """Explains the usage of this bot's other commands."""
            await interaction.response.send_message(
                'You have been `roles_help`ed.', ephemeral=True)

        # /roles_backup
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_backup(
            interaction: _discord.Interaction
        ) -> None:
            """Creates a backup file of members' display names and roles."""
            self._logger.info(f'Backing up: {interaction}')
            await interaction.response.send_message(
                'Backed up.')

        # /roles_restore
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        @_discord.app_commands.default_permissions(
            manage_nicknames=True,
            manage_roles=True)
        async def roles_restore(
            interaction: _discord.Interaction
        ) -> None:
            """Restores members' display names and roles from a backup file."""
            self._logger.info(f'Restoring: {interaction}')
            await interaction.response.send_message(
                'Restored.')

        # /roles_update
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        @_discord.app_commands.default_permissions(
            manage_nicknames=True,
            manage_roles=True)
        async def roles_update(
            interaction: _discord.Interaction
        ) -> None:
            """Modifies members' display names and roles based on the contents
            of a Google Sheet.
            """
            self._logger.info(f'Updating: {interaction}')
            await interaction.response.send_message(
                'Updated.', ephemeral=True)

        await self._slash_commands.sync(guild=guild)
        self._logger.info(f'Registered commands with guild: {guild}')




def main() -> None:
    """Entry point that logs the bot into Discord and executes commands until
    closed.
    """
    try:
        bot_token = _os.environ['SCHS_ROBOTICS_ROLES_BOT_TOKEN']
    except KeyError:
        import getpass
        bot_token = getpass.getpass(prompt='Bot token (input hidden): ')

    RolesBotClient().run(token=bot_token)




if __name__ == '__main__':
    main()
