#!/usr/bin/env python3
"""Starts the SCHS-Robotics-Roles-Bot that logs into Discord and answers
commands until closed.
"""


__version__ = '0.0.8'

__authors__ = ['James Abernathy']
__copyright__ = 'Copyright © 2023 James Abernathy'
__license__ = 'MIT'


import asyncio as _asyncio
import collections as _collections
import csv as _csv
import datetime as _datetime
import gzip as _gzip
import io as _io
import logging as _logging
import os as _os
import re as _re
import typing as _typing

import discord as _discord




TOKEN_ENV_NAME: _typing.Final[str] = 'SCHS_ROBOTICS_ROLES_BOT_TOKEN'
"""Environment variable name that :func:`.main` will attempt to read its Discord
bot token from.
"""




class CsvContentsError(ValueError):
    """Error raised when a backup CSV was missing rows or had values in the
    wrong format.
    """
    pass




class RolesBotClient(_discord.Client):
    """Discord bot client that connects to servers and responds to user app
    commands.
    """

    _logger: _logging.Logger
    """Top-level logger for this client."""

    _slash_commands: _discord.app_commands.CommandTree
    """Tree of available slash commands."""

    _guild_id_loggers: dict[int, _logging.Logger]
    """Server-specific loggers indexed by guild ID."""

    _guild_id_busy: dict[int, bool]
    """Server-specific busy flags indexed by guild ID and set ``True`` during
    backup, restore, and update operations.
    """


    _LOG_FILENAME: _typing.Final[str] = 'Log.txt.gz'
    """Filename of log attachment added to each command response."""

    _LOG_ENCODING: _typing.Final[str] = 'utf_8'
    """Text encoding of command log attachments."""


    _CSV_ENCODING: _typing.Final[str] = 'utf_8_sig'
    """Text encoding of CSV backups.  Include a UTF-8 byte-order marker so that
    importing into spreadsheets accurately detects the encoding.
    """

    _COLUMN_USER_ID: _typing.Final[str] = 'User ID'
    """CSV column header for string representations of members' integer user
    IDs.
    """

    _COLUMN_USERNAME: _typing.Final[str] = 'Username'
    """CSV column header for members' login usernames or discriminators."""

    _COLUMN_NICKNAME: _typing.Final[str] = 'Display Name'
    """CSV column header for members' server-specific display names."""

    _INVALID_ROLE_NAMES: _typing.Final[frozenset[str]] = frozenset([
        _COLUMN_USER_ID, _COLUMN_USERNAME, _COLUMN_NICKNAME])
    """Role names that can't be represented due to how :func:`csv.DictReader`
    and :func:`csv.DictWriter` coallesce duplicate column names.  See :gh:`1`.
    """


    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs,
            intents=_discord.Intents(
                members=True,  # Allow querying all guild members
                guilds=True),  # Receive on_guild_available events
            chunk_guilds_at_startup=False)

        self._logger = _logging.getLogger(
            f'{_discord.__name__}.{type(self).__name__}')
        self._logger.setLevel(_logging.DEBUG)

        self._guild_id_loggers = dict()
        self._guild_id_busy = dict()

        self._slash_commands = _discord.app_commands.CommandTree(self,
            fallback_to_global=False)


    async def on_ready(self) -> None:
        """Registers global slash commands with the server once logged in."""
        await self._slash_commands.sync()  # Global commands only
        self._logger.info(f'Logged on as “{self.user}”.')

    async def on_guild_available(self,
        guild: _discord.Guild
    ) -> None:
        """Registers the joined *guild*'s slash commands with the server."""
        self._guild_id_loggers[guild.id] = _logging.getLogger(
            f'{self._logger.name}.{guild.name.replace(".", "")}')
        self._guild_id_busy[guild.id] = False

        # /roles_help
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_help(
            interaction: _discord.Interaction
        ) -> None:
            """Explains the usage of this bot's other commands."""
            await self._command_roles_help(guild, interaction)

        # /roles_backup
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        async def roles_backup(
            interaction: _discord.Interaction
        ) -> None:
            """Creates a backup file of members' display names and roles."""
            await self._respond_to_long_command(guild, interaction,
                self._command_roles_backup)

        # /roles_restore <backup_file>
        @self._slash_commands.command(guild=guild)  # type: ignore[arg-type]
        @_discord.app_commands.guild_only()
        @_discord.app_commands.default_permissions(
            manage_nicknames=True,
            manage_roles=True)
        @_discord.app_commands.describe(
            backup_csv_gz='The gzipped CSV from `/roles_backup` to restore '
                'roles from.',
            dry_run='If enabled, only logs changes without applying them.  '
                'Disabled by default.')
        async def roles_restore(
            interaction: _discord.Interaction,
            backup_csv_gz: _discord.Attachment,
            dry_run: bool = False
        ) -> None:
            """Restores members' display names and roles from a backup file."""
            await self._respond_to_long_command(guild, interaction,
                self._command_roles_restore, backup_csv_gz, dry_run)

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
            await self._respond_to_long_command(guild, interaction,
                self._command_roles_update)

        await self._slash_commands.sync(guild=guild)
        self._guild_id_loggers[guild.id].info(
            f'Registered commands (Guild ID: {guild.id:x}).')


    class _GuildMember(object):
        """Stores relevant, mutable guild member details loaded from a guild or
        backup file.
        """

        _user_id: int
        """Backing field of read-only :func:`.user_id`."""

        _model: _typing.Optional[_discord.Member]
        """Backing field of read-only :func:`.model`."""

        username: str
        """Discord login name with or without a discriminator
        like ``#9999``.  Users may change this, so see :func:`.user_id` for a
        more permanent identifier.
        """

        nickname: _typing.Optional[str]
        """Server-specific name visible in the member list, or ``None`` if not
        customized in which case the display name falls back to a Discord-global
        display name or :attr:`username`.
        """

        role_names: set[str]
        """The names of all assigned roles."""

        def __init__(self,
            user_id: int,
            model: _typing.Optional[_discord.Member],
            username: str,
            nickname: _typing.Optional[str],
            role_names: set[str]
        ) -> None:
            self._user_id = user_id
            self._model = model
            self.username = username
            self.nickname = nickname
            self.role_names = role_names

        @classmethod
        def create_from_member(cls,
            member: _discord.Member,
            affected_roles: _collections.abc.Iterable[_discord.Role]
        ) -> _typing.Self:
            """Factory to construct a member queried from a Discord server."""
            return cls(user_id=member.id, model=member,
                username=str(member),  # New-style username or discriminator
                nickname=member.nick,
                role_names=set(role.name for role in affected_roles
                    if member.get_role(role.id) is not None))

        @classmethod
        def decode_csv_row(cls,
            member_row: dict[str, str]
        ) -> _typing.Self:
            """Factory to construct a member decoded from a backup CSV.  See
            :func:`.encode_csv_row`.
            """
            member_row = member_row.copy()
            try:
                user_id_text = member_row.pop(RolesBotClient._COLUMN_USER_ID)
                username = member_row.pop(RolesBotClient._COLUMN_USERNAME)
                nickname = member_row.pop(RolesBotClient._COLUMN_NICKNAME) or None
            except KeyError as e:
                raise CsvContentsError(f'Missing column “{e.args[0]}” in '
                    f'roles-backup CSV file.') from e

            # Parse ID
            try:
                user_id = int(_re.fullmatch(r'^#(?P<hex_digits>[0-9a-f]+)$',
                    user_id_text, _re.ASCII | _re.IGNORECASE
                    ).group('hex_digits'),  # type: ignore[union-attr]
                    base=16)
            except (AttributeError, ValueError) as e:
                raise CsvContentsError('Invalid '
                    f'“{RolesBotClient._COLUMN_USER_ID}” column value '
                    f'“{user_id_text}” in roles-backup CSV file.') from e

            # Parse roles
            role_names = set()
            for role_name, membership_text in member_row.items():
                try:
                    membership_int = int(membership_text)
                except ValueError as e:
                    raise CsvContentsError('Invalid decimal integer '
                        f'“{membership_text}” in user ID {user_id_text}\'s '
                        f'role column “{role_name}”.') from e
                if not (0 <= membership_int <= 1):
                    raise CsvContentsError(f'User ID {user_id_text}\'s role '
                        f'column “{role_name}” membership flag {membership_int} '
                        'must be either 0 or 1.')
                if bool(membership_int):
                    role_names.add(role_name)

            return cls(user_id=user_id, model=None,
                username=username, nickname=nickname, role_names=role_names)

        @property
        def user_id(self) -> int:
            """Globaly unique Discord user ID that will never change."""
            return self._user_id

        @property
        def model(self) -> _typing.Optional[_discord.Member]:
            """Reference to the live Discord representation of this member that
            this record was copied from, or ``None`` if not generated from live
            data.  Does not remain synced with this instance's members.
            """
            return self._model

        def copy(self) -> _typing.Self:
            """Creates a modifiable deep copy of this member."""
            return type(self)(
                user_id=self.user_id, model=self.model, username=self.username,
                nickname=self.nickname, role_names=self.role_names.copy())

        def encode_csv_row(self,
            affected_roles: _collections.abc.Iterable[_discord.Role]
        ) -> dict[str, str]:
            """Represents this member as a CSV row to be backed up.  See
            :func:`.decode_csv_row`.
            """
            return {
                # Prefix ID so spreadsheets interpret huge number as lossless text.
                RolesBotClient._COLUMN_USER_ID: f'#{self.user_id:x}',
                RolesBotClient._COLUMN_USERNAME: self.username,
                RolesBotClient._COLUMN_NICKNAME: self.nickname or '',
                # 0/1 booleans for each role
                **{role.name: str(int(role.name in self.role_names))
                    for role in affected_roles}}


    async def _respond_to_long_command(self,
        guild: _discord.Guild,
        interaction: _discord.Interaction,
        command_callback: _typing.Callable[...,
            _typing.Awaitable[list[_discord.File]]],
        *command_args: _typing.Any
    ) -> None:
        """Responds that the command is running, and then updates that response
        with the file attachments returned by *command_callback*.
        """
        guild_logger = self._guild_id_loggers[guild.id]
        command = _typing.cast(_discord.app_commands.Command, interaction.command)
        command_name = (f'`/{command.qualified_name}` '
            f'(Interaction ID: {interaction.id:x})')

        # Acquire exclusive access
        if self._guild_id_busy[guild.id]:
            await interaction.response.send_message(ephemeral=True,
                content=f'{command_name} ignored while another command is running.')
            return
        self._guild_id_busy[guild.id] = True
        try:
            # Respond with placeholder message
            message = f'{command_name} in progress…'
            guild_logger.info(message)
            await interaction.response.send_message(content=message)

            # Execute and send final response
            log_gz_file = _io.BytesIO()
            log_gz_attachment = _discord.File(log_gz_file, self._LOG_FILENAME)
            try:
                assert guild == interaction.guild, (
                    'Interaction originated from wrong guild '
                    f'“{interaction.guild}” (Guild ID: {interaction.guild_id:x}).')

                # Capture logs into an attachment
                with _gzip.GzipFile(mode='wb',
                    fileobj=log_gz_file, filename=self._LOG_FILENAME,
                    mtime=int(_datetime.datetime.now().timestamp())
                ) as log_bytes_file:
                    with _io.TextIOWrapper(
                        _typing.cast(_typing.IO[bytes], log_bytes_file),
                        encoding=self._LOG_ENCODING, errors='replace', newline=''
                    ) as log_file:
                        log_file_handler = _logging.StreamHandler(log_file)
                        guild_logger.addHandler(log_file_handler)
                        try:
                            # Execute long-running command
                            attachments = await command_callback(
                                guild, *command_args)
                        finally:
                            guild_logger.removeHandler(log_file_handler)
            except Exception as ex:
                # Embed exception in placeholder
                message = f'{command_name} failed:'
                ex_name = f'`{type(ex).__name__}`'
                ex_message = (
                    '```\n'
                    f'{_discord.utils.escape_markdown(str(ex))}\n'
                    '```')

                # Rewind log so Discord can read into an attachment.
                log_gz_file.seek(0)

                await interaction.edit_original_response(content=message,
                    embed=_discord.Embed(title=ex_name,
                        description=ex_message, type='rich',
                        color=_discord.Colour.brand_red()),
                    attachments=[log_gz_attachment])
                raise
            else:
                message = f'{command_name} succeeded.'
                guild_logger.info(message)

                # Rewind log so Discord can read into an attachment.
                log_gz_file.seek(0)

                # Attach files to placeholder
                attachments.insert(0, log_gz_attachment)
                await interaction.edit_original_response(content=message,
                    attachments=attachments)

        finally:  # Release exclusive access
            self._guild_id_busy[guild.id] = False


    async def _command_roles_help(self,
        guild: _discord.Guild,
        interaction: _discord.Interaction
    ) -> None:
        """Explains the usage of this bot's other commands."""
        await interaction.response.send_message(
            'You have been `roles_help`ed.', ephemeral=True)

    async def _command_roles_backup(self,
        guild: _discord.Guild
    ) -> list[_discord.File]:
        """Creates a backup file of members' display names and roles."""
        guild_logger = self._guild_id_loggers[guild.id]
        start_time = _datetime.datetime.now()
        backup_filename = f'Roles_Backup_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz'

        guild_logger.debug('Querying current members and roles…')
        affected_roles = self._get_affected_roles(guild)
        affected_members = await self._query_affected_members(guild, affected_roles)

        guild_logger.debug(f'Encoding {len(affected_members)} members with '
            f'{len(affected_roles)} possible roles into “{backup_filename}”…')
        return [self._encode_gzipped_csv(
            filename=backup_filename, creation_date=start_time,
            roles=affected_roles, members=affected_members)]

    async def _command_roles_restore(self,
        guild: _discord.Guild,
        csv_gz_attachment: _discord.Attachment,
        dry_run: bool = False
    ) -> list[_discord.File]:
        """Restores members' display names and roles from a backup file."""
        guild_logger = self._guild_id_loggers[guild.id]

        # Parse desired state
        guild_logger.debug(f'Decoding “{csv_gz_attachment.filename}”…')
        csv_gz_attachment_file = await csv_gz_attachment.to_file()
        backup_members_by_id = {backup_member.user_id: backup_member
            for backup_member in self._decode_gzipped_csv(csv_gz_attachment_file)}

        # Get current state
        guild_logger.debug('Querying current members and roles…')
        affected_roles = self._get_affected_roles(guild)
        affected_role_names = set(role.name for role in affected_roles)
        affected_roles_by_name = {role.name: role for role in affected_roles}
        affected_members = await self._query_affected_members(guild, affected_roles)

        # Ignore roles that no longer exist.
        missing_role_names = set()
        for backup_member in backup_members_by_id.values():
            missing_role_names.update(
                backup_member.role_names - affected_role_names)
            backup_member.role_names &= affected_role_names
        if missing_role_names:
            guild_logger.warning('Some roles from the backup no longer exist '
                f'or cannot be restored: {sorted(missing_role_names)}.')

        # Apply changes
        guild_logger.debug(f'Applying changes (`dry_run`={dry_run})…')
        reason = f'Restored role backup “{csv_gz_attachment.filename}”.'
        for affected_member, backup_member in (
            (affected_member, backup_members_by_id[affected_member.user_id])
            for affected_member in sorted(affected_members,
                key=lambda affected_member: affected_member.user_id)
            if affected_member.user_id in backup_members_by_id
        ):
            assert affected_member.model is not None
            username = (f'user “{affected_member.username}” '
                f'(ID {affected_member.user_id})')

            # Revert nickname
            if affected_member.nickname != backup_member.nickname:
                guild_logger.debug(f'Setting nickname of {username} to '
                    f'“{backup_member.nickname or ""}”.')
                if not dry_run:
                    try:
                        await affected_member.model.edit(
                            nick=backup_member.nickname, reason=reason)
                    except Exception as e:
                        guild_logger.warning(self._format_logged_exception(e))

            # Remove roles
            extra_role_names = affected_member.role_names - backup_member.role_names
            if extra_role_names:
                guild_logger.debug(
                    f'Removing roles from {username}: {sorted(extra_role_names)}.')
                if not dry_run:
                    try:
                        await affected_member.model.remove_roles(
                            *(affected_roles_by_name[extra_role_name]
                                for extra_role_name in extra_role_names),
                            reason=reason)
                    except Exception as e:
                        guild_logger.warning(self._format_logged_exception(e))

            # Add roles
            missing_role_names = backup_member.role_names - affected_member.role_names
            if missing_role_names:
                guild_logger.debug(
                    f'Adding roles to {username}: {sorted(missing_role_names)}.')
                if not dry_run:
                    try:
                        await affected_member.model.add_roles(
                            *(affected_roles_by_name[missing_role_name]
                                for missing_role_name in missing_role_names),
                            reason=reason)
                    except Exception as e:
                        guild_logger.warning(self._format_logged_exception(e))

        # Reattach input file
        return [csv_gz_attachment_file]

    async def _command_roles_update(self,
        guild: _discord.Guild
    ) -> list[_discord.File]:
        """Modifies members' display names and roles based on the contents
        of a Google Sheet.
        """
        start_time = _datetime.datetime.now()

        return [
            _discord.File(_io.BytesIO(b''), filename=
                f'Roles_Backup_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz'),
            _discord.File(_io.BytesIO(b''), filename=
                f'Roles_Update_{start_time:%Y-%m-%dT%H-%M-%S}.csv.gz')]


    def _get_affected_roles(self,
        guild: _discord.Guild
    ) -> list[_discord.Role]:
        """Lists roles from *guild* that the bot can affect, ordered by most
        to least privileged.
        """
        affected_roles = [role for role in reversed(guild.roles)
            if role.is_assignable()]  # Restorable by bot

        role_names_list = [role.name for role in affected_roles]
        role_names_set = set(role_names_list)
        if len(role_names_list) != len(role_names_set):
            duplicate_role_names = [role_name for role_name, repetitions
                in _collections.Counter(role_names_list).items()
                if repetitions > 1]
            raise CsvContentsError('Server contains roles with duplicate names: '
                f'{sorted(duplicate_role_names)}.')

        # Check if DictReader/DictWriter will fail (GitHub issue #1).
        invalid_role_names = role_names_set & self._INVALID_ROLE_NAMES
        if invalid_role_names:
            raise CsvContentsError('Server contains roles with invalid names: '
                f'{sorted(invalid_role_names)}.')

        return affected_roles

    async def _query_affected_members(self,
        guild: _discord.Guild,
        affected_roles: _collections.abc.Iterable[_discord.Role]
    ) -> list[_GuildMember]:
        """Gets *guild*'s members that the bot can affect, including their
        membership in *affected_roles*.
        """
        return [self._GuildMember.create_from_member(member, affected_roles)
            async for member in guild.fetch_members(limit=None)
            if member.top_role < guild.self_role]  # Restorable by bot


    def _encode_gzipped_csv(self,
        filename: str,
        creation_date: _datetime.datetime,
        roles: _collections.abc.Iterable[_discord.Role],
        members: _collections.abc.Iterable[_GuildMember]
    ) -> _discord.File:
        """Formats rows of *members* with columns including *roles*-membership
        as a gzip-compressed CSV attachment named *filename*.
        """
        csv_gz_file = _io.BytesIO()
        with _gzip.GzipFile(mode='wb', fileobj=csv_gz_file, filename=filename,
            mtime=int(creation_date.timestamp())
        ) as csv_bytes_file:
            with _io.TextIOWrapper(_typing.cast(_typing.IO[bytes], csv_bytes_file),
                encoding=self._CSV_ENCODING, errors='strict', newline=''
            ) as csv_file:
                csv_writer = _csv.DictWriter(csv_file, dialect='excel', fieldnames=[
                    self._COLUMN_USER_ID, self._COLUMN_USERNAME, self._COLUMN_NICKNAME,
                    *(role.name for role in roles)])

                csv_writer.writeheader()
                csv_writer.writerows(member.encode_csv_row(roles)
                    for member in sorted(members, key=lambda member: member.user_id))

        # Rewind so Discord can read into an attachment.
        csv_gz_file.seek(0)

        return _discord.File(csv_gz_file, filename)

    def _decode_gzipped_csv(self,
        csv_gz_file: _discord.File
    ) -> list[_GuildMember]:
        """Parses guild member data out of a *csv_gz_file* created by
        :func:`._encode_gzipped_csv`.
        """
        with _gzip.open(csv_gz_file.fp, mode='rt',
             encoding=self._CSV_ENCODING, errors='strict', newline=''
        ) as csv_file:
            csv_lines = _typing.cast(_collections.abc.Iterable[str], csv_file)

            members = [self._GuildMember.decode_csv_row(member_row)
                for member_row in _csv.DictReader(csv_lines,
                    dialect='excel', strict=True)]

        # Rewind so Discord can read into an attachment.
        csv_gz_file.fp.seek(0)

        return members

    @staticmethod
    def _format_logged_exception(
        exception: Exception
    ) -> str:
        """Formats *exception* and its chained exceptions using one line each
        without tracebacks for abbreviated logging purposes.
        """
        messages = []
        exception_current: _typing.Optional[BaseException] = exception
        while exception_current is not None:
            messages.append(
                f'{type(exception_current).__name__}: {exception_current}')
            exception_current = exception_current.__cause__
        return '\n'.join(messages)




def main() -> None:
    """Entry point that acquires a Discord bot token, logs in, and executes
    commands until closed.
    """
    try:
        bot_token = _os.environ[TOKEN_ENV_NAME]
    except KeyError:
        print(f'Bot token not found in environment variable “{TOKEN_ENV_NAME}”.')

        import getpass
        bot_token = getpass.getpass(prompt='Enter bot token (input hidden): ')

    RolesBotClient().run(token=bot_token)




if __name__ == '__main__':
    main()
