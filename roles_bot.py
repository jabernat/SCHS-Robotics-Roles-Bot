#!/usr/bin/env python3
"""Starts the SCHS-Robotics-Roles-Bot that logs into Discord and answers
commands until closed.
"""


__version__ = '0.0.4'

__authors__ = ['James Abernathy']
__copyright__ = 'Copyright © 2023 James Abernathy'
__license__ = 'MIT'


import asyncio as _asyncio
import csv as _csv
import datetime as _datetime
import gzip as _gzip
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
    """Top-level logger for this client."""

    _slash_commands: _discord.app_commands.CommandTree
    """Tree of available slash commands."""

    _guild_id_loggers: _typing.Dict[int, _logging.Logger]
    """Server-specific loggers indexed by guild ID."""

    _guild_id_busy: _typing.Dict[int, bool]
    """Server-specific busy flags indexed by guild ID and set ``true`` during
    backup, restore, and update operations.
    """


    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs,
            intents=_discord.Intents(
                members=True,  # Allow querying all guild members
                guilds=True),  # Receive on_guild_available events
            chunk_guilds_at_startup=False)

        self._logger = _logging.getLogger(
            f'{_discord.__name__}.{type(self).__name__}')

        self._guild_id_loggers = dict()
        self._guild_id_busy = dict()

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
        guild_logger = _logging.getLogger(
            f'{self._logger.name}.{guild.name.replace(".", "")}')
        self._guild_id_loggers[guild.id] = guild_logger
        self._guild_id_busy[guild.id] = False

        # /roles_help
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_help(
            interaction: _discord.Interaction
        ) -> None:
            """Explains the usage of this bot's other commands."""
            await self._command_roles_help(guild_logger, interaction)

        # /roles_backup
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_backup(
            interaction: _discord.Interaction
        ) -> None:
            """Creates a backup file of members' display names and roles."""
            await self._respond_to_long_command(guild_logger, interaction,
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
            await self._respond_to_long_command(guild_logger, interaction,
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
            await self._respond_to_long_command(guild_logger, interaction,
                self._command_roles_update)

        await self._slash_commands.sync(guild=guild)
        guild_logger.info(f'Registered commands with guild ID {guild.id:X}')


    async def _respond_to_long_command(self,
        logger: _logging.Logger,
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

        # Acquire exclusive access
        assert interaction.guild_id is not None
        if self._guild_id_busy[interaction.guild_id]:
            await interaction.response.send_message(ephemeral=True,
                content=f'{command_name} ignored while another command is running.')
            return
        self._guild_id_busy[interaction.guild_id] = True
        try:
            # Respond with placeholder message
            message = f'{command_name} in progress…'
            logger.info(message)
            await interaction.response.send_message(content=message)

            # Execute long-running command
            attachments: _typing.List[_discord.File]
            try:
                attachments = await command_callback(logger, interaction,
                    *command_args)
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
                logger.info(message)
                await interaction.edit_original_response(content=message,
                    attachments=attachments)

        finally:  # Release exclusive access
            self._guild_id_busy[interaction.guild_id] = False


    async def _command_roles_help(self,
        logger: _logging.Logger,
        interaction: _discord.Interaction
    ) -> None:
        """Explains the usage of this bot's other commands."""
        await interaction.response.send_message(
            'You have been `roles_help`ed.', ephemeral=True)

    async def _command_roles_backup(self,
        logger: _logging.Logger,
        interaction: _discord.Interaction
    ) -> _typing.List[_discord.File]:
        """Creates a backup file of members' display names and roles."""
        start_time = _datetime.datetime.now()
        filename = f'Roles_Backup_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz'

        csv_gz_file = _io.BytesIO()
        with _gzip.GzipFile(mode='wb', fileobj=csv_gz_file, filename=filename,
            mtime=int(start_time.timestamp())
        ) as csv_bytes_file, _io.TextIOWrapper(
            _typing.cast(_typing.IO[bytes], csv_bytes_file),
            encoding='utf_8', errors='strict', newline=''
        ) as csv_file:
            csv_writer = _csv.DictWriter(csv_file, dialect='excel', fieldnames=[
                'Username', 'Display Name', 'A', 'B', 'C'])
            csv_writer.writeheader()
            csv_writer.writerows([
                {'Username': 'x', 'Display Name': 'X', 'A': 1, 'B': 0, 'C': 0},
                {'Username': 'y', 'Display Name': 'Y', 'A': 0, 'B': 1, 'C': 0},
                {'Username': 'z', 'Display Name': 'Z', 'A': 0, 'B': 0, 'C': 1}])

        csv_gz_file.seek(0)
        return [_discord.File(csv_gz_file, filename=filename)]

    async def _command_roles_restore(self,
        logger: _logging.Logger,
        interaction: _discord.Interaction,
        csv_gz_attachment: _discord.Attachment
    ) -> _typing.List[_discord.File]:
        """Restores members' display names and roles from a backup file."""
        csv_gz_attachment_file = await csv_gz_attachment.to_file()
        with _gzip.open(csv_gz_attachment_file.fp, mode='rt',
             encoding='utf_8', errors='strict', newline=''
        ) as csv_file:
            csv_lines = _typing.cast(_typing.Iterable[str], csv_file)
            for row in _csv.DictReader(csv_lines, dialect='excel', strict=True):
                logger.info(row)

        csv_gz_attachment_file.fp.seek(0)
        return [csv_gz_attachment_file]

    async def _command_roles_update(self,
        logger: _logging.Logger,
        interaction: _discord.Interaction
    ) -> _typing.List[_discord.File]:
        """Modifies members' display names and roles based on the contents
        of a Google Sheet.
        """
        start_time = _datetime.datetime.now()

        return [
            _discord.File(_io.BytesIO(b''), filename=
                f'Roles_Backup_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz'),
            _discord.File(_io.BytesIO(b''), filename=
                f'Roles_Update_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz')]




def main() -> None:
    """Entry point that logs the bot into Discord and executes commands until
    closed.
    """
    token_env_name = 'SCHS_ROBOTICS_ROLES_BOT_TOKEN'
    try:
        bot_token = _os.environ[token_env_name]
    except KeyError:
        print(f'Bot token not found in environment variable “{token_env_name}”.')

        import getpass
        bot_token = getpass.getpass(prompt='Enter bot token (input hidden): ')

    RolesBotClient().run(token=bot_token)




if __name__ == '__main__':
    main()
