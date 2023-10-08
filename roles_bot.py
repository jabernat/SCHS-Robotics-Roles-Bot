#!/usr/bin/env python3
"""Starts the SCHS-Robotics-Roles-Bot that logs into Discord and answers
commands until closed.
"""


__version__ = '0.0.2'

__authors__ = ['James Abernathy']
__copyright__ = 'Copyright © 2023 James Abernathy'
__license__ = 'MIT'


import asyncio as _asyncio
import datetime as _datetime
import io as _io
import logging as _logging
import os as _os
import typing as _typing

import discord as _discord




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
        """Registers global slash commands with the server once logged in."""
        await self._slash_commands.sync()  # Global commands only
        self._logger.info(f'Logged on as {self.user}.')

    async def on_guild_available(self,
        guild: _discord.Guild
    ) -> None:
        """Registers joined guild's slash commands with the server."""

        # /roles_help
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_help(
            interaction: _discord.Interaction
        ) -> None:
            """Explains the usage of this bot's other commands."""
            await self._command_roles_help(interaction)

        # /roles_backup
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_backup(
            interaction: _discord.Interaction
        ) -> None:
            """Creates a backup file of members' display names and roles."""
            await self._respond_to_long_command(interaction,
                self._command_roles_backup)

        # /roles_restore <backup_file>
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        @_discord.app_commands.default_permissions(
            manage_nicknames=True,
            manage_roles=True)
        async def roles_restore(
            interaction: _discord.Interaction,
            backup_csv_gz: _discord.Attachment
        ) -> None:
            """Restores members' display names and roles from a backup file."""
            await self._respond_to_long_command(interaction,
                self._command_roles_restore, backup_csv_gz)

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
            await self._respond_to_long_command(interaction,
                self._command_roles_update)

        await self._slash_commands.sync(guild=guild)
        self._logger.info(f'Registered commands with guild: {guild}')


    async def _respond_to_long_command(self,
        interaction: _discord.Interaction,
        command_callback: _typing.Callable[...,
            _typing.Awaitable[_typing.List[_discord.File]]],
        *command_args: _typing.Any
    ) -> None:
        """Responds that the command is running, and then updates that response
        with the file attachments returned by `command_callback`.
        """
        command = _typing.cast(_discord.app_commands.Command, interaction.command)
        command_name = f'`/{command.qualified_name}` (ID {interaction.id:X})'

        # Respond with placeholder message
        message = f'{command_name} in progress…'
        self._logger.info(message)
        await interaction.response.send_message(content=message)

        attachments: _typing.List[_discord.File]
        try:
            attachments = await command_callback(interaction, *command_args)

        except Exception as ex:
            # Embed exception in placeholder
            message = f'{command_name} failed.'
            await interaction.edit_original_response(content=message,
                embed=_discord.Embed(type='rich',
                    title=type(ex).__name__, color=_discord.Colour.brand_red(),
                    description=f'```\n{_discord.utils.escape_markdown(str(ex))}\n```'))
            raise

        else:
            # Attach files to placeholder
            message = f'{command_name} succeeded.'
            self._logger.info(message)
            await interaction.edit_original_response(content=message,
                attachments=attachments)


    async def _command_roles_help(self,
        interaction: _discord.Interaction
    ) -> None:
        """Explains the usage of this bot's other commands."""
        await interaction.response.send_message(
            'You have been `roles_help`ed.', ephemeral=True)

    async def _command_roles_backup(self,
        interaction: _discord.Interaction
    ) -> _typing.List[_discord.File]:
        """Creates a backup file of members' display names and roles."""
        start_time = _datetime.datetime.now()
        await _asyncio.sleep(5)
        return [_discord.File(_io.BytesIO(b''), filename=
            f'Roles_Backup_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz')]

    async def _command_roles_restore(self,
        interaction: _discord.Interaction,
        csv_gz_attachment: _discord.Attachment
    ) -> _typing.List[_discord.File]:
        """Restores members' display names and roles from a backup file."""
        csv_gz_bytes = await csv_gz_attachment.read()
        await _asyncio.sleep(5)
        return [
            await csv_gz_attachment.to_file()]

    async def _command_roles_update(self,
        interaction: _discord.Interaction
    ) -> _typing.List[_discord.File]:
        """Modifies members' display names and roles based on the contents
        of a Google Sheet.
        """
        start_time = _datetime.datetime.now()
        await _asyncio.sleep(5)
        return [
            _discord.File(_io.BytesIO(b''), filename=
                f'Roles_Backup_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz'),
            _discord.File(_io.BytesIO(b''), filename=
                f'Roles_Update_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz')]




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
