import asyncio
import logging
import os

import aiohttp
from rich.logging import RichHandler
from rich.markdown import Markdown
from rich.traceback import install
from streamrip.console import console
from streamrip.rip.cli import latest_streamrip_version
from streamrip.rip.main import Main
from streamrip.config import Config, OutdatedConfigError, set_user_defaults, DEFAULT_CONFIG_PATH
from streamrip import __version__

logger = logging.getLogger(__name__)
CODECS = ("ALAC", "FLAC", "OGG", "MP3", "AAC")


def rip(
    *,
    config_path: str = DEFAULT_CONFIG_PATH,
    folder: str | None = None,
    no_db: bool = False,
    codec: str | None = None,
    quality: int | None = None,
    verbose: bool = False,
):
    """Streamrip: the all in one music downloader."""
    logging.basicConfig(
        level="INFO",
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler()],
    )
    logger = logging.getLogger("streamrip")
    if verbose:
        install(
            console=console,
            show_locals=True,
            locals_hide_sunder=False,
        )
        logger.setLevel(logging.DEBUG)
        logger.debug("Showing all debug logs")
    else:
        install(console=console, suppress=[asyncio], max_frames=1)
        logger.setLevel(logging.INFO)

    if not os.path.isfile(config_path):
        console.print(
            f"No file found at [bold cyan]{config_path}[/bold cyan], creating default config.",
        )
        set_user_defaults(config_path)

    try:
        c = Config(config_path)
    except OutdatedConfigError as e:
        console.print(e)
        console.print("Auto-updating config file...")
        Config.update_file(config_path)
        c = Config(config_path)
    except Exception as e:
        console.print(
            f"Error loading config from [bold cyan]{config_path}[/bold cyan]: {e}\n"
            "Try running [bold]rip config reset[/bold]",
        )
        return

    # set session config values to command line args
    if no_db:
        c.session.database.downloads_enabled = False
    if folder is not None:
        c.session.downloads.folder = folder

    if quality is not None:
        c.session.tidal.quality = quality

    if codec is not None:
        c.session.conversion.enabled = True
        assert codec.upper() in CODECS
        c.session.conversion.codec = codec.upper()
    return c


async def url(urls: list[str], config: Config | None):
    if config is None:
        return

    try:
        with config as cfg:
            cfg: Config
            updates = cfg.session.misc.check_for_updates
            if updates:
                # Run in background
                version_coro = asyncio.create_task(
                    latest_streamrip_version(verify_ssl=cfg.session.downloads.verify_ssl)
                )
            else:
                version_coro = None

            async with Main(cfg) as main:
                await main.add_all(urls)
                await main.resolve()
                await main.rip()

            if version_coro is not None:
                latest_version, notes = await version_coro
                if latest_version != __version__:
                    console.print(
                        f"\n[green]A new version of streamrip [cyan]v{latest_version}[/cyan]"
                        " is available! Run [white][bold]pip3 install streamrip --upgrade[/bold][/white]"
                        " to update.[/green]\n"
                    )

                    console.print(Markdown(notes))

    except aiohttp.ClientConnectorCertificateError as e:
        from streamrip.utils.ssl_utils import print_ssl_error_help

        console.print(f"[red]SSL Certificate verification error: {e}[/red]")
        print_ssl_error_help()


if __name__ == "__main__":
    urls = ["https://tidal.com/playlist/1f5eac89-e94c-4ca9-9487-3db8376e05f0"]  # English
    config = rip(folder="C:/Users/techn/PycharmProjects/MusicPlayer/music_player/export2")
    asyncio.run(url(urls, config))
